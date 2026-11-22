"""限气排单事务编排测试：用内存假连接验证幂等、回滚退额与余量重算。

不依赖 PostgreSQL/psycopg/sklearn，运行：python3 -m tests.test_shift_plan
"""
import os
import sys
import types
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ---- 依赖桩：避免引入 psycopg / sklearn / fastapi -----------------------
psycopg_pkg = types.ModuleType('psycopg')
psycopg_types = types.ModuleType('psycopg.types')
psycopg_json = types.ModuleType('psycopg.types.json')
psycopg_json.Jsonb = lambda value: ('jsonb', value)
psycopg_types.json = psycopg_json
psycopg_rows = types.ModuleType('psycopg.rows')
psycopg_rows.dict_row = object
psycopg_pkg.types = psycopg_types
psycopg_pkg.rows = psycopg_rows
sys.modules['psycopg'] = psycopg_pkg
sys.modules['psycopg.types'] = psycopg_types
sys.modules['psycopg.types.json'] = psycopg_json
sys.modules['psycopg.rows'] = psycopg_rows

fastapi_pkg = types.ModuleType('fastapi')
fastapi_encoders = types.ModuleType('fastapi.encoders')


def jsonable_encoder(value):
    from datetime import datetime
    from decimal import Decimal
    if isinstance(value, dict):
        return {str(key): jsonable_encoder(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable_encoder(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


fastapi_encoders.jsonable_encoder = jsonable_encoder
fastapi_pkg.encoders = fastapi_encoders
fastapi_pkg.Depends = lambda *a, **k: None
fastapi_pkg.HTTPException = type('HTTPException', (Exception,), {'__init__': lambda self, *a, **k: None})
fastapi_security = types.ModuleType('fastapi.security')
fastapi_security.HTTPAuthorizationCredentials = object
fastapi_security.HTTPBearer = lambda *a, **k: None
sys.modules['fastapi'] = fastapi_pkg
sys.modules['fastapi.encoders'] = fastapi_encoders
sys.modules['fastapi.security'] = fastapi_security

# regression.py 顶部导入 numpy 与 sklearn，测试只用其函数入口，给空模块桩即可。
numpy_stub = types.ModuleType('numpy')
sys.modules['numpy'] = numpy_stub
sklearn_stub = types.ModuleType('sklearn')
linear_stub = types.ModuleType('sklearn.linear_model')
linear_stub.ElasticNetCV = object
metrics_stub = types.ModuleType('sklearn.metrics')
metrics_stub.mean_absolute_error = lambda *a: 0.0
selection_stub = types.ModuleType('sklearn.model_selection')
selection_stub.KFold = object
selection_stub.train_test_split = lambda *a, **k: (None,) * 4
pipeline_stub = types.ModuleType('sklearn.pipeline')
pipeline_stub.make_pipeline = lambda *a: None
preprocessing_stub = types.ModuleType('sklearn.preprocessing')
preprocessing_stub.StandardScaler = object
for name, module in [('sklearn', sklearn_stub), ('sklearn.linear_model', linear_stub),
                     ('sklearn.metrics', metrics_stub), ('sklearn.model_selection', selection_stub),
                     ('sklearn.pipeline', pipeline_stub), ('sklearn.preprocessing', preprocessing_stub)]:
    sys.modules[name] = module

jwt_stub = types.ModuleType('jwt')
jwt_stub.encode = lambda *a, **k: 'token'
jwt_stub.decode = lambda *a, **k: {}
jwt_stub.InvalidTokenError = type('InvalidTokenError', (Exception,), {})
sys.modules['jwt'] = jwt_stub
redis_stub = types.ModuleType('redis')
redis_stub.RedisError = type('RedisError', (Exception,), {})
sys.modules['redis'] = redis_stub

# 轻量 pydantic 桩：测试只实例化 SimpleNamespace，无需真实校验层。
pydantic_stub = types.ModuleType('pydantic')


class _BaseModel:
    def __init__(self, **kwargs):
        vars(self).update(kwargs)

    def model_dump(self):
        return dict(vars(self))


pydantic_stub.BaseModel = _BaseModel
pydantic_stub.Field = lambda default=None, **kwargs: default
pydantic_stub.StringConstraints = lambda **kwargs: str
pydantic_stub.AwareDatetime = object
pydantic_stub.model_validator = lambda mode='after': (lambda func: func)
sys.modules['pydantic'] = pydantic_stub

from kiln import scheduling, shift_plan
from kiln.ledger import LedgerError

shift_plan.audit = lambda conn, batch, actor, event, **detail: conn.audits.append((event, detail))


class Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows if rows is not None else ([row] if row is not None else [])

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConn:
    """按 SQL 片段分派的最小内存连接，表用 dict/list 保存。"""

    def __init__(self):
        self.shifts = {}
        self.programs = []
        self.reservations = []
        self.requests = {}
        self.batches = []
        self.audits = []
        self.rollbacks = 0
        self.commits = 0
        self._snapshot = None
        self._next_reservation = 1

    # 保存点：进入时快照，回滚时恢复，模拟真实事务内回滚退额。
    def transaction(self):
        outer = self

        class Savepoint:
            def __enter__(self_inner):
                outer._snapshot = outer._dump()

            def __exit__(self_inner, exc_type, exc, tb):
                if exc_type is not None:
                    outer._load(outer._snapshot)
                    outer.rollbacks += 1
                    return False
                return False
        return Savepoint()

    def commit(self):
        self.commits += 1

    def _dump(self):
        import copy
        return copy.deepcopy({'reservations': self.reservations, 'requests': self.requests,
                               'audits': self.audits, 'next': self._next_reservation})

    def _load(self, snapshot):
        import copy
        state = copy.deepcopy(snapshot)
        self.reservations = state['reservations']
        self.requests = state['requests']
        self.audits = state['audits']
        self._next_reservation = state['next']

    def execute(self, sql, params=()):
        s = ' '.join(sql.split())
        if 'pg_advisory_xact_lock' in s:
            return Result()
        if 'SELECT * FROM gas_shifts WHERE id=%s' in s:
            return Result(self.shifts.get(params[0]))
        if s.startswith('SELECT * FROM shift_plan_requests WHERE request_key=%s FOR UPDATE'):
            return Result(self.requests.get(params[0]))
        if 'FROM firing_programs WHERE recipe=%s AND version<=%s' in s:
            recipe, version = params
            matches = [p for p in self.programs if p['recipe'] == recipe and p['version'] <= version]
            return Result(matches[0] if matches else None)
        if 'FROM firing_batches b' in s and 'NOT EXISTS' in s:
            end, start = params
            reserved_codes = {r['batch_code'] for r in self.reservations}
            rows = [dict(b) for b in self.batches
                    if b['opened_at'] < end and b['closed_at'] > start and b['code'] not in reserved_codes
                    and b['code'] not in self._batches_with_runs()]
            return Result(rows=rows)
        if 'sum(reserved_m3),0) AS used FROM shift_reservations' in s:
            total = sum((r['reserved_m3'] for r in self.reservations if r['shift_id'] == params[0]), Decimal('0'))
            return Result({'used': total})
        if s.startswith('INSERT INTO shift_reservations'):
            shift_id, code, reserved_m3, batch_kg, _, actor = params
            self.reservations.append({'id': self._next_reservation, 'shift_id': shift_id, 'batch_code': code,
                                      'reserved_m3': reserved_m3, 'batch_kg': batch_kg, 'requested_by': actor})
            self._next_reservation += 1
            return Result()
        if s.startswith('INSERT INTO shift_plan_requests'):
            key, shift_id, actor, detail = params
            status = 'failed' if "'failed'" in s else 'placed'
            self.requests[key] = {'request_key': key, 'shift_id': shift_id, 'actor': actor,
                                  'status': status, 'detail': detail[1]}
            return Result()
        if 'FROM shift_reservations r JOIN firing_batches b' in s:
            rows = []
            for r in self.reservations:
                if r['shift_id'] == params[0]:
                    batch = next(b for b in self.batches if b['code'] == r['batch_code'])
                    rows.append({**r, 'kiln': batch['kiln'], 'recipe': batch['recipe'],
                                 'baseline_version': batch['baseline_version'],
                                 'planned_minutes': batch['planned_minutes'], 'opened_at': batch['opened_at'],
                                 'closed_at': batch['closed_at'], 'batch_status': batch['status']})
            return Result(rows=rows)
        if s.startswith('DELETE FROM shift_reservations'):
            shift_id, code = params
            before = len(self.reservations)
            removed = next((r for r in self.reservations
                            if r['shift_id'] == shift_id and r['batch_code'] == code), None)
            self.reservations = [r for r in self.reservations
                                 if not (r['shift_id'] == shift_id and r['batch_code'] == code)]
            return Result({'reserved_m3': removed['reserved_m3']} if len(self.reservations) < before else None)
        raise AssertionError(f'未模拟的 SQL: {s}')

    def _batches_with_runs(self):
        return set()


# ---- 测试夹具 -----------------------------------------------------------
def form(request_key):
    return types.SimpleNamespace(request_key=request_key)


def make_conn():
    conn = FakeConn()
    conn.shifts[1] = {'id': 1, 'name': '1122 早班限气', 'quota_m3': Decimal('200.000'),
                      'started_at': 100, 'ended_at': 900}
    conn.programs.append({'recipe': '釉面砖 Y17', 'version': 3,
                          'ramp_peak_c': Decimal('1050'), 'soak_peak_c': Decimal('1180'),
                          'cool_peak_c': Decimal('1000'), 'ramp_share': Decimal('0.375'),
                          'soak_share': Decimal('0.250')})
    base = {'recipe': '釉面砖 Y17', 'baseline_version': 3, 'planned_minutes': 480,
            'opened_at': 0, 'closed_at': 1000, 'kiln': 'K2 辊道窑', 'status': 'scheduled'}
    # 假模型回归：估算气量稳定为 装载kg/10，便于手算组合。
    conn.batches = [
        {**base, 'code': 'K1-1122-A', 'batch_kg': Decimal('900.00')},   # 90 m³
        {**base, 'code': 'K1-1122-B', 'batch_kg': Decimal('1200.00')},  # 120 m³
        {**base, 'code': 'K1-1122-C', 'batch_kg': Decimal('700.00')},   # 70 m³
    ]
    return conn


def patch_regression():
    def fake_plan_features(batch_kg, planned_minutes, program):
        return [float(batch_kg)]
    shift_plan.regression.plan_features = fake_plan_features
    shift_plan.regression.predict_features = lambda model, features: round(features[0] / 10, 3)
    shift_plan.regression.fit_model = lambda: (object(), {'mae_m3': 2.4})
    shift_plan.regression.FEATURES = ['batch_kg']


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print('ok -', name)


def test_first_plan_picks_max_kg_within_quota():
    patch_regression()
    conn = make_conn()
    # 额度 200：A(90)+C(70)=160 气/1600kg；B(120)+C(70)=190 气/1900kg 最优。
    result = shift_plan.plan_shift(conn, 1, form('REQ-0001-0001'), 'firing')
    check('首次排单非幂等返回', result['idempotent'] is False)
    check('选出 B+C 使总装载量最大', result['placed_codes'] == ['K1-1122-B', 'K1-1122-C'])
    check('预留气量合计 190', result['placed_total_m3'] == 190.0)
    check('预留落库两条', len(conn.reservations) == 2)
    check('余量为 10 m³', result['shift']['remaining_m3'] == Decimal('10.000'))


def test_retry_same_key_is_idempotent_and_does_not_deduct_again():
    patch_regression()
    conn = make_conn()
    first = shift_plan.plan_shift(conn, 1, form('REQ-0002-0002'), 'firing')
    second = shift_plan.plan_shift(conn, 1, form('REQ-0002-0002'), 'firing')
    check('重试标记为幂等', second['idempotent'] is True)
    check('重试返回同一组合', second['placed_codes'] == first['placed_codes'])
    check('占额没有重复扣减', len(conn.reservations) == 2)
    check('审计记录了重放', any(event == 'shift_plan_replayed' for event, _ in conn.audits))


def test_failed_plan_rolls_back_and_retry_does_not_deduct():
    patch_regression()
    conn = make_conn()
    conn.shifts[1]['quota_m3'] = Decimal('50.000')  # 最小候选 70 气，谁都排不下
    try:
        shift_plan.plan_shift(conn, 1, form('REQ-0003-0003'), 'firing')
        raise AssertionError('应当因额度不足失败')
    except LedgerError as error:
        check('失败码为额度不足', error.code == 'QUOTA_INSUFFICIENT')
    check('失败后无任何占额', conn.reservations == [])
    check('保存点回滚发生', conn.rollbacks == 1)
    check('失败请求已登记', conn.requests['REQ-0003-0003']['status'] == 'failed')
    # 同一请求键重试：返回首次失败，且仍不产生占额。
    try:
        shift_plan.plan_shift(conn, 1, form('REQ-0003-0003'), 'firing')
        raise AssertionError('重试应复现首次失败')
    except LedgerError as error:
        check('重试复现首次失败码', error.code == 'QUOTA_INSUFFICIENT')
    check('重试仍未扣气', conn.reservations == [])


def test_release_returns_quota_and_recompute_uses_new_remaining():
    patch_regression()
    conn = make_conn()
    shift_plan.plan_shift(conn, 1, form('REQ-0004-0004'), 'firing')
    detail = shift_plan.release_reservation(conn, 1, 'K1-1122-C', 'firing')
    check('释放后余量回到 80', detail['remaining_m3'] == Decimal('80.000'))
    check('占额只剩 B', [r['batch_code'] for r in conn.reservations] == ['K1-1122-B'])
    # C 重新成为候选；余量 80 只能再排 C(70)，重算后只纳入 C。
    again = shift_plan.plan_shift(conn, 1, form('REQ-0005-0005'), 'firing')
    check('余量变化后重算纳入 C', again['placed_codes'] == ['K1-1122-C'])
    check('A 因剩余额度不足落选', {row['code'] for row in again['rejected']} == {'K1-1122-A'})


def test_missing_program_blocks_without_reservation():
    patch_regression()
    conn = make_conn()
    conn.programs.clear()
    try:
        shift_plan.plan_shift(conn, 1, form('REQ-0006-0006'), 'firing')
        raise AssertionError('缺少温程应当拦截')
    except LedgerError as error:
        check('缺温程报 PROGRAM_MISSING', error.code == 'PROGRAM_MISSING')
    check('拦截后不留占额', conn.reservations == [])


if __name__ == '__main__':
    test_first_plan_picks_max_kg_within_quota()
    test_retry_same_key_is_idempotent_and_does_not_deduct_again()
    test_failed_plan_rolls_back_and_retry_does_not_deduct()
    test_release_returns_quota_and_recompute_uses_new_remaining()
    test_missing_program_blocks_without_reservation()
    print('all shift_plan tests passed')
