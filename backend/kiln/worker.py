import logging
import time
from pathlib import Path

from psycopg import Error
from psycopg.types.json import Jsonb
from redis import RedisError

from .infra import audit, connect, queue
from .regression import estimate

HEARTBEAT = Path('/tmp/kiln-heartbeat')
logging.basicConfig(level=logging.INFO)


def process_next(preferred_id=None):
    with connect() as conn:
        pending = conn.execute("""SELECT r.id FROM load_runs r JOIN firing_batches b ON b.code=r.batch_code
            WHERE r.status='queued' ORDER BY CASE WHEN r.id=%s THEN 0 ELSE 1 END, r.id
            FOR UPDATE OF b SKIP LOCKED LIMIT 1""", (preferred_id,)).fetchone()
        if not pending:
            return False
        run = conn.execute('SELECT * FROM load_runs WHERE id=%s FOR UPDATE', (pending['id'],)).fetchone()
        try:
            result = estimate(run['input_snapshot'])
        except Exception as exc:
            logging.exception('Load run %s failed', run['id'])
            conn.execute("UPDATE load_runs SET status='failed',error=%s,attempts=attempts+1 WHERE id=%s",
                         (type(exc).__name__, run['id']))
            audit(conn, run['batch_code'], 'worker', 'load_failed', run_id=run['id'], kind=type(exc).__name__)
        else:
            conn.execute("UPDATE load_runs SET status='ready',result=%s,attempts=attempts+1 WHERE id=%s",
                         (Jsonb(result), run['id']))
            conn.execute("UPDATE firing_batches SET status='analyzed' WHERE code=%s AND status<>'confirmed'", (run['batch_code'],))
            audit(conn, run['batch_code'], 'worker', 'load_ready', run_id=run['id'], delta_m3=result['delta_m3'])
        return True


def work_forever():
    redis = queue()
    while True:
        HEARTBEAT.touch()
        try:
            message = redis.brpop('kiln:load:wake', timeout=2)
        except RedisError:
            message = None
            time.sleep(1)
        run_id = int(message[1]) if message and message[1].isdigit() else None
        try:
            process_next(run_id)
        except Error:
            logging.exception('Database queue unavailable')
            time.sleep(2)


if __name__ == '__main__':
    work_forever()
