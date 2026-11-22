from .infra import audit
from .ledger import batch_row, require
from .schemas import BatchStatus


def new_recipe(conn, code, form, actor):
    batch = batch_row(conn, code, lock=True)
    require(batch['status'] != BatchStatus.confirmed, 'CYCLE_CLOSED', '周期已确认')
    require(not conn.execute("SELECT 1 FROM recipe_changes WHERE batch_code=%s AND status='pending'", (code,)).fetchone(),
            'PENDING_RECIPE', '请先处理尚未审批的配方变更')
    prior = conn.execute('SELECT max(version) AS version FROM recipe_changes WHERE batch_code=%s', (code,)).fetchone()
    version = (prior['version'] or batch['baseline_version']) + 1
    row = conn.execute('''INSERT INTO recipe_changes(batch_code,version,description,submitted_by)
        VALUES (%s,%s,%s,%s) RETURNING *''', (code, version, form.description, actor)).fetchone()
    audit(conn, code, actor, 'recipe_proposed', version=version)
    return row


def decide_recipe(conn, code, change_id, form, actor):
    batch = batch_row(conn, code, lock=True)
    require(batch['status'] != BatchStatus.confirmed, 'CYCLE_CLOSED', '周期已确认')
    row = conn.execute('''UPDATE recipe_changes SET status=%s,reviewed_by=%s,note=%s,reviewed_at=now()
        WHERE batch_code=%s AND id=%s AND status='pending' AND submitted_by<>%s RETURNING *''',
        (form.decision, actor, form.note, code, change_id, actor)).fetchone()
    require(row, 'RECIPE_NOT_DECIDABLE', '配方必须由不同于提报人的主管审批，已审批的记录不可覆盖')
    audit(conn, code, actor, 'recipe_' + form.decision, version=row['version'], note=form.note)
    return row


def review_recipe(conn, code, run, attribution):
    if attribution == 'observed':
        return None
    change = conn.execute('SELECT * FROM recipe_changes WHERE batch_code=%s ORDER BY version DESC LIMIT 1', (code,)).fetchone()
    require(change and change['status'] == 'approved', 'RECIPE_UNAPPROVED', '最新配方尚未获批，不能把低负荷归入配方复核')
    require(run['result']['actual_m3'] < run['result']['expected_m3'], 'NO_LOAD_REDUCTION',
            '实测用量未低于模型参考值，不能记录为配方降耗')
    return change['id']


def propose_cycle(conn, code, form, actor):
    batch = batch_row(conn, code, lock=True)
    require(batch['status'] == BatchStatus.analyzed, 'LOAD_NOT_READY', '请先取得负荷试算结果，已确认周期不可修改')
    run = conn.execute("SELECT * FROM load_runs WHERE id=%s AND batch_code=%s AND status='ready'",
                       (form.run_id, code)).fetchone()
    require(run, 'LOAD_NOT_READY', '该周期没有对应的已完成试算')
    change_id = review_recipe(conn, code, run, form.attribution)
    row = conn.execute('''INSERT INTO cycle_reviews(batch_code,run_id,recipe_change_id,next_minutes,attribution,rationale,proposed_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(batch_code) DO UPDATE SET run_id=excluded.run_id,
        recipe_change_id=excluded.recipe_change_id,next_minutes=excluded.next_minutes,attribution=excluded.attribution,
        rationale=excluded.rationale,proposed_by=excluded.proposed_by RETURNING *''',
        (code, form.run_id, change_id, form.next_minutes, form.attribution, form.rationale, actor)).fetchone()
    audit(conn, code, actor, 'cycle_proposed', run_id=form.run_id, input_hash=run['input_hash'], change_id=change_id,
          minutes=form.next_minutes, attribution=form.attribution, rationale=form.rationale)
    return row


def confirm_cycle(conn, code, actor):
    batch = batch_row(conn, code, lock=True)
    require(batch['status'] == BatchStatus.analyzed, 'CYCLE_NOT_CONFIRMABLE', '该周期暂不可确认')
    review = conn.execute('SELECT * FROM cycle_reviews WHERE batch_code=%s', (code,)).fetchone()
    require(review and review['proposed_by'] != actor, 'INDEPENDENT_CONFIRMATION', '节拍方案需要由另一位主管确认')
    run = conn.execute('SELECT * FROM load_runs WHERE id=%s', (review['run_id'],)).fetchone()
    change_id = review_recipe(conn, code, run, review['attribution'])
    require(change_id == review['recipe_change_id'], 'RECIPE_REVISION_CHANGED', '配方版本已变化，请重提节拍方案')
    row = conn.execute('''UPDATE cycle_reviews SET confirmed_by=%s,confirmed_at=now()
                           WHERE batch_code=%s RETURNING *''', (actor, code)).fetchone()
    conn.execute("UPDATE firing_batches SET status='confirmed' WHERE code=%s", (code,))
    audit(conn, code, actor, 'cycle_confirmed', run_id=run['id'], input_hash=run['input_hash'],
          change_id=change_id, minutes=row['next_minutes'])
    return row
