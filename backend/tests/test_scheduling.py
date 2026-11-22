"""限气排单组合优化的纯算法测试，运行：python3 -m tests.test_scheduling"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from kiln.scheduling import (GAS_SCALE, WEIGHT_SCALE, choose_combination,
                             gas_to_milli, milli_to_m3, weight_to_units)


def item(code, gas_m3, kg):
    return {'code': code, 'gas_milli': gas_to_milli(gas_m3),
            'weight_units': weight_to_units(kg)}


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print('ok -', name)


def test_basic_knapsack_prefers_total_kg():
    # 额度 100：A(60气,80kg) + C(35气,50kg)=130kg；B(80气,120kg) 单件 120kg。
    candidates = [item('K-A', 60, 80), item('K-B', 80, 120), item('K-C', 35, 50)]
    chosen, gas, weight, rejected = choose_combination(candidates, gas_to_milli(100))
    check('总装载量最大的组合入选', chosen == {'K-A', 'K-C'})
    check('气量合计为 95 m³', gas == gas_to_milli(95))
    check('装载合计为 130 kg', weight == weight_to_units(130))
    check('落选包含 B', [row['code'] for row in rejected] == ['K-B'])


def test_tie_keeps_cheaper_gas_plan():
    # 两组同为 100kg：X 耗气 60，Y 耗气 55，应取更省气的 Y。
    candidates = [item('K-X', 60, 100), item('K-Y', 55, 100)]
    chosen, gas, _, _ = choose_combination(candidates, gas_to_milli(100))
    check('同装载量取气量更省', chosen == {'K-Y'})
    check('省气方案气量为 55', gas == gas_to_milli(55))


def test_deterministic_ordering_under_equal_plans():
    # 额度 40 只能容纳一件，两件等价时固定取批次号靠前的 K-A。
    candidates = [item('K-Z', 40, 90), item('K-A', 40, 90)]
    first, *_ = choose_combination(candidates, gas_to_milli(40))
    second, *_ = choose_combination(list(reversed(candidates)), gas_to_milli(40))
    check('输入顺序不影响结果', first == second == {'K-A'})


def test_zero_capacity_rejects_all():
    candidates = [item('K-A', 10, 20)]
    chosen, gas, weight, rejected = choose_combination(candidates, 0)
    check('零额度无窑次入选', chosen == set() and gas == 0 and weight == 0)
    check('零额度全部落选', len(rejected) == 1)


def test_milli_rounding_exact():
    from decimal import Decimal
    check('气量按千分之一取整', gas_to_milli(12.3456) == 12346)
    check('毫立方米还原三位小数', milli_to_m3(12346) == Decimal('12.346'))
    check('装载量按百分之一取整', weight_to_units(1170.25) == 117025)
    check('缩放常量稳定', GAS_SCALE == 1000 and WEIGHT_SCALE == 100)


def test_reserved_quota_blocks_overweight_batch():
    # 已占 70，剩余 30：只有 C(25) 能排，A(40)、B(60) 落选。
    candidates = [item('K-A', 40, 120), item('K-B', 60, 160), item('K-C', 25, 60)]
    chosen, gas, weight, rejected = choose_combination(candidates, gas_to_milli(30))
    check('剩余额度只容纳 C', chosen == {'K-C'})
    check('C 的气量与装载', gas == gas_to_milli(25) and weight == weight_to_units(60))
    check('A、B 均落选', {row['code'] for row in rejected} == {'K-A', 'K-B'})


def test_matches_bruteforce_on_random_cases():
    # 与 2^n 穷举结果对照：随机规模不超过 12 件，容量与气量均为小整数。
    import random
    rng = random.Random(1073)
    for case in range(300):
        n = rng.randint(1, 12)
        capacity = rng.randint(0, 200)
        candidates = [{'code': f'K{i:02d}', 'gas_milli': rng.randint(1, 90),
                       'weight_units': rng.randint(1, 200)} for i in range(n)]
        chosen, gas, weight, _ = choose_combination(candidates, capacity)
        best_weight, best_gas = 0, 0
        for mask in range(1 << n):
            combo = [candidates[i] for i in range(n) if mask & (1 << i)]
            combo_gas = sum(c['gas_milli'] for c in combo)
            combo_weight = sum(c['weight_units'] for c in combo)
            if combo_gas <= capacity and (combo_weight > best_weight or
                                          (combo_weight == best_weight and combo_gas < best_gas)):
                best_weight, best_gas = combo_weight, combo_gas
        check(f'随机案例 {case} 装载量最优', weight == best_weight)
        check(f'随机案例 {case} 气量最省且不超额', gas == best_gas and gas <= capacity)


if __name__ == '__main__':
    test_basic_knapsack_prefers_total_kg()
    test_tie_keeps_cheaper_gas_plan()
    test_deterministic_ordering_under_equal_plans()
    test_zero_capacity_rejects_all()
    test_milli_rounding_exact()
    test_reserved_quota_blocks_overweight_batch()
    test_matches_bruteforce_on_random_cases()
    print('all scheduling tests passed')
