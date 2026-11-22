"""限气班次的额度、计划温程与排单事务。

并发口径：所有排单/释放操作先取班次级咨询锁（pg_advisory_xact_lock），
在同一事务内读取最新余量并重算组合，因此两组并发确认共用额度、互不覆盖。
幂等口径：排单请求带 request_key，重试命中已登记请求时原样返回，不重复扣气；
未排上的窑次在事务内不落占额记录，失败即整体回滚，额度自动退回。
"""
from decimal import Decimal

from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from . import regression, scheduling
from .infra import audit
from .ledger import LedgerError, require

MODEL_REVISION = 'en-20261121-plan'
# 班次级咨询锁的固定编号空间，避免与 hashtext 的窑炉锁混用。
SHIFT_LOCK_NAMESPACE = 91073


def shift_lock(conn, shift_id):
    conn.execute('SELECT pg_advisory_xact_lock(%s, %s)', (SHIFT_LOCK_NAMESPACE, shift_id))


def shift_row(conn, shift_id, lock=False):
    sql = 'SELECT * FROM gas_shifts WHERE id=%s' + (' FOR UPDATE' if lock else '')
    row = conn.execute(sql, (shift_id,)).fetchone()
    require(row, 'UNKNOWN_SHIFT', '限气班次不存在', 404)
    return row


def list_shifts(conn):
    return conn.execute('''SELECT s.*,
        (SELECT count(*) FROM shift_reservations r WHERE r.shift_id=s.id) AS reserved_batches,
        COALESCE((SELECT sum(r.reserved_m3) FROM shift_reservations r WHERE r.shift_id=s.id),0) AS reserved_m3
        FROM gas_shifts s ORDER BY s.started_at DESC, s.id DESC''').fetchall()


def shift_detail(conn, shift_id):
    shift = shift_row(conn, shift_id)
    reservations = conn.execute('''SELECT r.*, b.kiln, b.recipe, b.baseline_version, b.planned_minutes,
        b.opened_at, b.closed_at, b.status AS batch_status
        FROM shift_reservations r JOIN firing_batches b ON b.code=r.batch_code
        WHERE r.shift_id=%s ORDER BY r.id''', (shift_id,)).fetchall()
    reserved_m3 = sum((row['reserved_m3'] for row in reservations), Decimal('0'))
    return {**shift, 'reserved_m3': reserved_m3,
            'remaining_m3': shift['quota_m3'] - reserved_m3,
            'reservations': reservations}


def create_shift(conn, form, actor):
    row = conn.execute('''INSERT INTO gas_shifts(name,started_at,ended_at,quota_m3,created_by)
        VALUES (%(name)s,%(started_at)s,%(ended_at)s,%(quota_m3)s,%(actor)s)
        ON CONFLICT DO NOTHING RETURNING *''', {**form.model_dump(), 'actor': actor}).fetchone()
    require(row, 'DUPLICATE_SHIFT', '班次名称已存在')
    audit(conn, None, actor, 'shift_created', shift_id=row['id'], name=row['name'],
          quota_m3=float(row['quota_m3']))
    return row


def create_program(conn, form, actor):
    row = conn.execute('''INSERT INTO firing_programs(recipe,version,ramp_peak_c,soak_peak_c,cool_peak_c,
        ramp_share,soak_share,created_by) VALUES (%(recipe)s,%(version)s,%(ramp_peak_c)s,%(soak_peak_c)s,
        %(cool_peak_c)s,%(ramp_share)s,%(soak_share)s,%(actor)s) ON CONFLICT DO NOTHING RETURNING *''',
        {**form.model_dump(), 'actor': actor}).fetchone()
    require(row, 'DUPLICATE_PROGRAM', '该配方版本的计划温程已存在')
    audit(conn, None, actor, 'program_created', recipe=row['recipe'], version=row['version'])
    return row


def list_programs(conn):
    return conn.execute('SELECT * FROM firing_programs ORDER BY recipe, version DESC').fetchall()


def program_for_batch(conn, batch):
    return conn.execute('''SELECT * FROM firing_programs WHERE recipe=%s AND version<=%s
        ORDER BY version DESC LIMIT 1''', (batch['recipe'], batch['baseline_version'])).fetchone()


def estimate_batch(conn, model, metrics, batch):
    """按计划装载和温程做回归估算，返回 (预留气量 Decimal, 估算快照 dict)。"""
    program = program_for_batch(conn, batch)
    require(program, 'PROGRAM_MISSING',
            f"窑次 {batch['code']} 的配方 {batch['recipe']} 缺少计划温程，无法估算用气量", 422)
    features = regression.plan_features(batch['batch_kg'], batch['planned_minutes'], program)
    expected_m3 = regression.predict_features(model, features)
    require(expected_m3 > 0, 'NONPOSITIVE_ESTIMATE', f"窑次 {batch['code']} 的估算气量非正，不能排单", 422)
    snapshot = {'basis': 'planned', 'model_revision': MODEL_REVISION, 'model_metrics': metrics,
                'cycle': {'code': batch['code'], 'recipe': batch['recipe'],
                          'baseline_version': batch['baseline_version'], 'batch_kg': float(batch['batch_kg']),
                          'planned_minutes': batch['planned_minutes']},
                'program': {key: float(program[key]) for key in
                            ('ramp_peak_c', 'soak_peak_c', 'cool_peak_c', 'ramp_share', 'soak_share')},
                'features': dict(zip(regression.FEATURES, features)), 'expected_m3': expected_m3}
    return scheduling.milli_to_m3(scheduling.gas_to_milli(expected_m3)), snapshot


def candidate_batches(conn, shift):
    """与班次时段相交、尚未采集试算、且未在任何班次占额的已登记窑次。"""
    return conn.execute('''SELECT b.* FROM firing_batches b
        WHERE b.opened_at < %s AND b.closed_at > %s
          AND NOT EXISTS (SELECT 1 FROM load_runs r WHERE r.batch_code=b.code)
          AND NOT EXISTS (SELECT 1 FROM shift_reservations x WHERE x.batch_code=b.code)
        ORDER BY b.code''', (shift['ended_at'], shift['started_at'])).fetchall()


def plan_shift(conn, shift_id, form, actor):
    shift_lock(conn, shift_id)
    # 幂等：同一请求键的重试原样返回，绝不二次扣气。
    prior = conn.execute('SELECT * FROM shift_plan_requests WHERE request_key=%s FOR UPDATE',
                         (form.request_key,)).fetchone()
    if prior:
        audit(conn, None, actor, 'shift_plan_replayed', shift_id=shift_id, request_key=form.request_key,
              status=prior['status'])
        if prior['status'] == 'failed':
            detail = prior['detail']
            raise LedgerError(detail.get('error_code', 'PLAN_FAILED'),
                              detail.get('reason', '排单失败，请更换请求键后重试'))
        return {'idempotent': True, **prior['detail']}
    try:
        # 保存点：业务规则失败时回滚占额改动，但保留失败请求记录，使重试命中幂等键。
        with conn.transaction():
            return _plan_locked(conn, shift_id, form, actor)
    except LedgerError as error:
        conn.execute('''INSERT INTO shift_plan_requests(request_key,shift_id,actor,status,detail)
            VALUES (%s,%s,%s,'failed',%s) ON CONFLICT (request_key) DO NOTHING''',
                     (form.request_key, shift_id, actor,
                      Jsonb({'error_code': error.code, 'reason': error.message})))
        audit(conn, None, actor, 'shift_plan_failed', shift_id=shift_id, request_key=form.request_key,
              code=error.code, reason=error.message)
        conn.commit()
        raise


def _plan_locked(conn, shift_id, form, actor):
    shift = shift_row(conn, shift_id, lock=True)
    batches = candidate_batches(conn, shift)
    require(batches, 'NO_CANDIDATE', '班次时段内没有可排的窑次', 422)

    model, metrics = regression.fit_model()
    estimates = {}
    for batch in batches:
        reserved_m3, snapshot = estimate_batch(conn, model, metrics, batch)
        estimates[batch['code']] = {'batch': batch, 'reserved_m3': reserved_m3, 'snapshot': snapshot}

    reserved = conn.execute('SELECT COALESCE(sum(reserved_m3),0) AS used FROM shift_reservations WHERE shift_id=%s',
                            (shift_id,)).fetchone()['used']
    remaining_m3 = shift['quota_m3'] - reserved
    capacity = scheduling.gas_to_milli(remaining_m3)
    require(capacity >= 0, 'QUOTA_EXCEEDED', '已排窑次预留气量超过班次额度，请先释放占额')
    candidates = [{'code': code,
                   'gas_milli': scheduling.gas_to_milli(item['reserved_m3']),
                   'weight_units': scheduling.weight_to_units(item['batch']['batch_kg'])}
                  for code, item in estimates.items()]
    chosen, total_gas, total_weight, rejected = scheduling.choose_combination(candidates, capacity)
    require(chosen, 'QUOTA_INSUFFICIENT', '剩余额度不足以排下任何候选窑次', 422)

    for code in sorted(chosen):
        item = estimates[code]
        conn.execute('''INSERT INTO shift_reservations(shift_id,batch_code,reserved_m3,batch_kg,
            estimate_snapshot,requested_by) VALUES (%s,%s,%s,%s,%s,%s)''',
                     (shift_id, code, item['reserved_m3'], item['batch']['batch_kg'],
                      Jsonb(jsonable_encoder(item['snapshot'])), actor))
    detail = shift_detail(conn, shift_id)
    plan = {'shift': detail, 'placed_codes': sorted(chosen),
            'placed_total_m3': float(scheduling.milli_to_m3(total_gas)),
            'placed_total_kg': total_weight / scheduling.WEIGHT_SCALE,
            'rejected': rejected, 'estimates': {code: item['snapshot'] for code, item in estimates.items()}}
    conn.execute('''INSERT INTO shift_plan_requests(request_key,shift_id,actor,status,detail)
        VALUES (%s,%s,%s,'placed',%s)''', (form.request_key, shift_id, actor, Jsonb(jsonable_encoder(plan))))
    audit(conn, None, actor, 'shift_plan_placed', shift_id=shift_id, request_key=form.request_key,
          placed=sorted(chosen), total_m3=plan['placed_total_m3'])
    return {'idempotent': False, **plan}


def release_reservation(conn, shift_id, code, actor):
    shift_lock(conn, shift_id)
    shift_row(conn, shift_id, lock=True)
    row = conn.execute('''DELETE FROM shift_reservations WHERE shift_id=%s AND batch_code=%s
        RETURNING reserved_m3''', (shift_id, code)).fetchone()
    require(row, 'NOT_RESERVED', '该窑次未在此班次预留气量，无需退回', 404)
    audit(conn, code, actor, 'shift_reservation_released', shift_id=shift_id,
          released_m3=float(row['reserved_m3']))
    return shift_detail(conn, shift_id)
