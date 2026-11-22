from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .operations_evidence import router as operations_evidence
from . import ledger, reviews, schemas as forms
from .infra import allow, audit, connect, identity, publish_run, queue, token, verify_password

app = FastAPI(title='陶瓷窑炉燃气负荷回归')
app.include_router(operations_evidence)
operator = allow('operator')
supervisor = allow('supervisor')


@app.middleware('http')
async def request_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Request-ID'] = str(uuid4())
    return response


@app.middleware('http')
async def response_policy(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ledger.LedgerError)
async def handle_rule(request: Request, error: ledger.LedgerError):
    return JSONResponse({'code': error.code, 'detail': error.message}, status_code=error.status)


@app.exception_handler(RequestValidationError)
async def handle_invalid(request: Request, error: RequestValidationError):
    fields = [str(item['loc'][-1]) for item in error.errors()]
    return JSONResponse({'code': 'INVALID_INPUT', 'detail': '请检查字段：' + '、'.join(fields)}, status_code=422)


def mutate(operation, code, actor):
    try:
        with connect() as conn:
            return operation(conn)
    except ledger.LedgerError as error:
        with connect() as conn:
            audit(conn, code, actor, 'rule_blocked', code=error.code, reason=error.message)
        raise


@app.get('/health')
def health():
    with connect() as conn:
        conn.execute('SELECT code FROM firing_batches LIMIT 1')
    queue().ping()
    return {'status': 'ok'}


@app.post('/login')
def sign_in(form: forms.Credentials):
    with connect() as conn:
        account = conn.execute('SELECT * FROM accounts WHERE username=%s', (form.username,)).fetchone()
        if not account or not verify_password(form.password, account['password_digest']):
            raise HTTPException(401, '工号或密码有误')
        return {'token': token(account), 'user': {'username': account['username'], 'role': account['role']}}


@app.get('/batches')
def overview(user=Depends(identity)):
    with connect() as conn:
        return ledger.list_batches(conn)


@app.get('/batches/{code}')
def detail(code: str, user=Depends(identity)):
    with connect() as conn:
        return ledger.dossier(conn, code)


@app.post('/batches', status_code=201)
def schedule(form: forms.Batch, actor=Depends(operator)):
    return mutate(lambda conn: ledger.create_batch(conn, form, actor), form.code, actor)


@app.post('/batches/{code}/curve', status_code=201)
def add_curve(code: str, form: forms.CurveSegment, actor=Depends(operator)):
    return mutate(lambda conn: ledger.record_curve(conn, code, form, actor), code, actor)


@app.post('/batches/{code}/curve/{phase}/withdraw')
def withdraw(code: str, phase: forms.Phase, form: forms.RecipeProposal, actor=Depends(operator)):
    mutate(lambda conn: ledger.withdraw_curve(conn, code, phase, form.description, actor), code, actor)
    return {'status': 'withdrawn'}


@app.post('/batches/{code}/meter', status_code=201)
def add_meter(code: str, form: forms.MeterSample, actor=Depends(operator)):
    return mutate(lambda conn: ledger.record_meter(conn, code, form, actor), code, actor)


@app.post('/batches/{code}/runs', status_code=202)
def run_load(code: str, actor=Depends(operator)):
    record = mutate(lambda conn: ledger.request_load(conn, code, actor), code, actor)
    if record['status'] == 'queued':
        publish_run(record['id'])
    return record


@app.post('/batches/{code}/runs/{run_id}/retry', status_code=202)
def retry(code: str, run_id: int, actor=Depends(supervisor)):
    record = mutate(lambda conn: ledger.retry_load(conn, code, run_id, actor), code, actor)
    publish_run(record['id'])
    return record


@app.post('/batches/{code}/recipes', status_code=201)
def add_recipe(code: str, form: forms.RecipeProposal, actor=Depends(operator)):
    return mutate(lambda conn: reviews.new_recipe(conn, code, form, actor), code, actor)


@app.post('/batches/{code}/recipes/{change_id}/decision')
def rule_recipe(code: str, change_id: int, form: forms.RecipeDecision, actor=Depends(supervisor)):
    return mutate(lambda conn: reviews.decide_recipe(conn, code, change_id, form, actor), code, actor)


@app.post('/batches/{code}/review')
def propose(code: str, form: forms.ReviewPlan, actor=Depends(operator)):
    return mutate(lambda conn: reviews.propose_cycle(conn, code, form, actor), code, actor)


@app.post('/batches/{code}/review/confirm')
def confirm(code: str, actor=Depends(supervisor)):
    return mutate(lambda conn: reviews.confirm_cycle(conn, code, actor), code, actor)
