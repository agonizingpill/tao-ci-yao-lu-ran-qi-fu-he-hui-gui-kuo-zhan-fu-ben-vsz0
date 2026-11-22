from datetime import datetime, timedelta, timezone

from kiln.infra import connect, password_digest

SHOP_TZ = timezone(timedelta(hours=8))


def seed():
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('kiln-demo-seed'))")
        for username, role in [('firing', 'operator'), ('chief', 'supervisor'), ('energy', 'viewer')]:
            present = conn.execute('SELECT 1 FROM accounts WHERE username=%s', (username,)).fetchone()
            if not present:
                conn.execute('INSERT INTO accounts VALUES (%s,%s,%s)', (username, password_digest('KilnLab!1073'), role))
        for day, code, kiln, mass, base, total, completeness in [
            (21, 'K2-1121-A', 'K2 辊道窑', 1170, 1250.400, 112.700, 'gap'),
            (20, 'K2-1120-B', 'K2 辊道窑', 1260, 1095.100, 155.300, 'full'),
            (21, 'K1-1121-C', 'K1 辊道窑', 910, 450.700, 121.400, 'scheduled'),
        ]:
            start = datetime(2026, 11, day, 6, tzinfo=SHOP_TZ)
            end = start + timedelta(hours=8)
            added = conn.execute('''INSERT INTO firing_batches VALUES (%s,%s,'釉面砖 Y17',3,%s,%s,%s,480,%s,'firing')
                ON CONFLICT DO NOTHING RETURNING code''', (code, kiln, mass, start, end,
                                                            'scheduled' if completeness == 'scheduled' else 'recording')).fetchone()
            if not added or completeness == 'scheduled':
                continue
            for phase, a, b, peak in [('ramp', 0, 3, 1050), ('soak', 3, 5, 1180), ('cool', 5, 8, 1000)]:
                if completeness == 'gap' and phase == 'soak':
                    continue
                conn.execute('INSERT INTO kiln_curve VALUES (%s,%s,%s,%s,%s,%s,\'firing\')',
                             (code, phase, start + timedelta(hours=a), start + timedelta(hours=b), peak, f'{code}-TC.csv'))
            for hours, fraction in [(0, 0), (2, .27), (4, .61), (6, .87), (8, 1)]:
                if completeness == 'gap' and hours == 4:
                    continue
                conn.execute('INSERT INTO gas_meter VALUES (%s,%s,\'GM-K2-08\',%s,%s,\'firing\')',
                             (code, start + timedelta(hours=hours), round(base + total * fraction, 3), f'{code}-GAS.csv'))
        counts = {name: conn.execute(f'SELECT count(*) AS n FROM {name}').fetchone()['n'] for name in
                  ('accounts', 'firing_batches', 'kiln_curve', 'gas_meter', 'recipe_changes', 'load_runs', 'cycle_reviews', 'ledger_audit')}
        print('seed ledger', counts)


if __name__ == '__main__':
    seed()
