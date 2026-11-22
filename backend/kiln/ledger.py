import hashlib
import json
from datetime import timedelta

from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from .infra import audit
from .schemas import BatchStatus, Phase


class LedgerError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status


def require(condition, code, message, status=409):
    if not condition:
        raise LedgerError(code, message, status)


def batch_row(conn, code, lock=False):
    sql = 'SELECT * FROM firing_batches WHERE code=%s' + (' FOR UPDATE' if lock else '')
    batch = conn.execute(sql, (code,)).fetchone()
    require(batch, 'UNKNOWN_BATCH', '烧成批次不存在', 404)
    return batch


def list_batches(conn):
    return conn.execute('''SELECT b.*,
        (SELECT count(*) FROM kiln_curve c WHERE c.batch_code=b.code) AS phases,
        (SELECT count(*) FROM gas_meter m WHERE m.batch_code=b.code) AS samples,
        (SELECT status FROM load_runs r WHERE r.batch_code=b.code ORDER BY id DESC LIMIT 1) AS load_status
        FROM firing_batches b ORDER BY opened_at DESC, code''').fetchall()


def raw_readings(conn, code):
    curves = conn.execute('SELECT * FROM kiln_curve WHERE batch_code=%s ORDER BY started_at', (code,)).fetchall()
    samples = conn.execute('SELECT * FROM gas_meter WHERE batch_code=%s ORDER BY sampled_at', (code,)).fetchall()
    return curves, samples


def dossier(conn, code):
    batch = batch_row(conn, code)
    curves, samples = raw_readings(conn, code)
    return {**batch, 'curves': curves, 'meters': samples,
            'recipes': conn.execute('SELECT * FROM recipe_changes WHERE batch_code=%s ORDER BY version DESC', (code,)).fetchall(),
            'runs': conn.execute('''SELECT id,batch_code,status,input_hash,result,error,attempts,created_at,input_snapshot
                                    FROM load_runs WHERE batch_code=%s ORDER BY id DESC''', (code,)).fetchall(),
            'review': conn.execute('SELECT * FROM cycle_reviews WHERE batch_code=%s', (code,)).fetchone(),
            'audit': conn.execute('SELECT * FROM ledger_audit WHERE batch_code=%s ORDER BY id DESC LIMIT 60', (code,)).fetchall()}


def create_batch(conn, form, actor):
    conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (form.kiln,))
    overlap = conn.execute('''SELECT 1 FROM firing_batches WHERE kiln=%s AND opened_at < %s AND closed_at > %s''',
                           (form.kiln, form.closed_at, form.opened_at)).fetchone()
    require(not overlap, 'KILN_BUSY', '该窑炉同一时段已有烧成批次')
    row = conn.execute('''INSERT INTO firing_batches(code,kiln,recipe,baseline_version,batch_kg,opened_at,closed_at,
        planned_minutes,created_by) VALUES (%(code)s,%(kiln)s,%(recipe)s,%(baseline_version)s,%(batch_kg)s,
        %(opened_at)s,%(closed_at)s,%(planned_minutes)s,%(actor)s)
        ON CONFLICT DO NOTHING RETURNING *''', {**form.model_dump(), 'actor': actor}).fetchone()
    require(row, 'DUPLICATE_BATCH', '批次号已存在')
    audit(conn, form.code, actor, 'firing_scheduled', kiln=form.kiln)
    return row


def recording_batch(conn, code):
    batch = batch_row(conn, code, lock=True)
    require(batch['status'] in (BatchStatus.scheduled, BatchStatus.recording), 'SOURCE_FROZEN',
            '已提交试算的原始记录已冻结')
    require(not conn.execute('SELECT 1 FROM load_runs WHERE batch_code=%s', (code,)).fetchone(),
            'SOURCE_FROZEN', '已提交试算的原始记录已冻结')
    return batch


def record_curve(conn, code, form, actor):
    batch = recording_batch(conn, code)
    require(batch['opened_at'] <= form.started_at < form.ended_at <= batch['closed_at'],
            'CURVE_OUTSIDE_CYCLE', '曲线段必须落在该烧成周期内')
    overlaps = conn.execute('''SELECT 1 FROM kiln_curve WHERE batch_code=%s AND started_at < %s AND ended_at > %s''',
                            (code, form.ended_at, form.started_at)).fetchone()
    require(not overlaps, 'CURVE_OVERLAP', '曲线段不能重叠')
    row = conn.execute('''INSERT INTO kiln_curve VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING RETURNING *''', (code, form.phase.value, form.started_at, form.ended_at,
                                               form.peak_c, form.source_file, actor)).fetchone()
    require(row, 'PHASE_EXISTS', '该温度阶段已经登记')
    conn.execute("UPDATE firing_batches SET status='recording' WHERE code=%s", (code,))
    audit(conn, code, actor, 'curve_recorded', phase=form.phase.value, source=form.source_file)
    return row


def record_meter(conn, code, form, actor):
    batch = recording_batch(conn, code)
    require(batch['opened_at'] <= form.sampled_at <= batch['closed_at'], 'METER_OUTSIDE_CYCLE', '抄表时间超出烧成周期')
    samples = conn.execute('SELECT * FROM gas_meter WHERE batch_code=%s ORDER BY sampled_at', (code,)).fetchall()
    for sample in samples:
        require(sample['meter_serial'] == form.meter_serial, 'METER_MISMATCH', '同批次必须使用同一台燃气总表')
        require(sample['sampled_at'] != form.sampled_at, 'DUPLICATE_READING', '该时点已有抄表记录')
        before = sample['sampled_at'] < form.sampled_at
        valid = sample['reading_m3'] <= form.reading_m3 if before else form.reading_m3 <= sample['reading_m3']
        require(valid, 'COUNTER_ROLLBACK', '累计立方米不能倒退，请核对原始表单')
    row = conn.execute('INSERT INTO gas_meter VALUES (%s,%s,%s,%s,%s,%s) RETURNING *',
                       (code, form.sampled_at, form.meter_serial, form.reading_m3, form.source_file, actor)).fetchone()
    conn.execute("UPDATE firing_batches SET status='recording' WHERE code=%s", (code,))
    audit(conn, code, actor, 'meter_recorded', sample=form.sampled_at.isoformat(), source=form.source_file)
    return row


def check_coverage(batch, curves, samples):
    cursor = batch['opened_at']
    for curve in curves:
        require(curve['started_at'] == cursor, 'CURVE_GAP', '曲线有空档，请补登相邻阶段后再试算')
        cursor = curve['ended_at']
    require(cursor == batch['closed_at'] and [row['phase'] for row in curves] == [p.value for p in Phase],
            'CURVE_GAP', '曲线必须依次覆盖升温、保温和冷却至出窑')
    require(len(samples) >= 2 and samples[0]['sampled_at'] == batch['opened_at'] and
            samples[-1]['sampled_at'] == batch['closed_at'], 'METER_GAP', '须有进窑和出窑时点的累计抄表')
    require(all(right['sampled_at'] - left['sampled_at'] <= timedelta(hours=3)
                for left, right in zip(samples, samples[1:])), 'METER_GAP', '两次累计抄表间隔超过三小时，请补登中间读数')


def request_load(conn, code, actor):
    batch = batch_row(conn, code, lock=True)
    require(batch['status'] != BatchStatus.confirmed, 'CYCLE_CLOSED', '周期已确认')
    curves, samples = raw_readings(conn, code)
    check_coverage(batch, curves, samples)
    snapshot = jsonable_encoder({'cycle': {key: batch[key] for key in ('code', 'recipe', 'baseline_version', 'batch_kg',
                                                                      'opened_at', 'closed_at', 'planned_minutes')},
                                 'curve': curves, 'meter': samples, 'model_revision': 'en-20261121'})
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    row = conn.execute('''INSERT INTO load_runs(batch_code,input_hash,input_snapshot,requested_by) VALUES (%s,%s,%s,%s)
        ON CONFLICT DO NOTHING RETURNING id,status,input_hash''', (code, digest, Jsonb(snapshot), actor)).fetchone()
    if row:
        audit(conn, code, actor, 'load_queued', run_id=row['id'], input_hash=digest)
        return row
    return conn.execute('SELECT id,status,input_hash FROM load_runs WHERE batch_code=%s AND input_hash=%s',
                        (code, digest)).fetchone()


def retry_load(conn, code, run_id, actor):
    batch_row(conn, code, lock=True)
    row = conn.execute("""UPDATE load_runs SET status='queued',error=NULL WHERE batch_code=%s AND id=%s
                         AND status='failed' RETURNING id,status,input_hash""", (code, run_id)).fetchone()
    require(row, 'NOT_RETRYABLE', '只有失败的试算可以重试')
    audit(conn, code, actor, 'load_requeued', run_id=run_id, input_hash=row['input_hash'])
    return row


def withdraw_curve(conn, code, phase, reason, actor):
    recording_batch(conn, code)
    row = conn.execute('DELETE FROM kiln_curve WHERE batch_code=%s AND phase=%s RETURNING *',
                       (code, phase.value)).fetchone()
    require(row, 'UNKNOWN_PHASE', '该温度阶段尚未登记', 404)
    audit(conn, code, actor, 'curve_withdrawn', reason=reason, original=jsonable_encoder(row))
