"""限气班次排单的纯算法部分。

气量以千分之一立方米（毫立方米）为整数单位，装载量以百分之一千克（十克）为整数单位，
避免浮点比较导致的组合抖动。组合优化是 0-1 背包：在燃气额度内最大化总装载量。
"""

GAS_SCALE = 1000      # 1 m³ = 1000 毫立方米
WEIGHT_SCALE = 100    # 1 kg = 100 个百分之一千克单位


def gas_to_milli(value_m3):
    return int(round(float(value_m3) * GAS_SCALE))


def weight_to_units(value_kg):
    return int(round(float(value_kg) * WEIGHT_SCALE))


def milli_to_m3(value_milli):
    from decimal import Decimal
    return (Decimal(value_milli) / GAS_SCALE).quantize(Decimal('0.001'))


def _better(candidate, current):
    """装载量更高者优；装载量相同时气量占用更少者优；都相同时保留先处理项。

    items 已按批次号排序，先处理即批次号字典序靠前，等值不覆盖可得到确定组合。
    """
    cand_weight, cand_gas = candidate
    cur_weight, cur_gas = current
    return cand_weight > cur_weight or (cand_weight == cur_weight and cand_gas < cur_gas)


def choose_combination(candidates, capacity_milli):
    """在燃气额度内挑选窑次组合，最大化总装载量。

    candidates: 列表，元素含 code、gas_milli（正整数）、weight_units（正整数）。
    capacity_milli: 班次剩余额度（毫立方米，非负整数）。
    返回 (选中的 code 集合, 选中气量合计, 选中装载量合计, 落选明细)。
    候选先按批次号排序，装载量与气量均相同时取得字典序靠前的确定组合，
    保证两组并发确认在相同余量下重算结果一致。
    """
    items = sorted(candidates, key=lambda item: item['code'])
    width = capacity_milli + 1
    # 滚动数组保存每行的最优 (装载量, 气量)；kept[i][w] 仅用一个字节记录第 i 件是否选入，
    # 避免完整二维对象表在大额度下占用过多内存。
    previous = [(0, 0)] * width
    kept = [bytearray(width) for _ in items]
    for i, item in enumerate(items):
        gas, weight = item['gas_milli'], item['weight_units']
        current = previous.copy()
        for w in range(gas, width):
            base_weight, base_gas = previous[w - gas]
            candidate = (base_weight + weight, base_gas + gas)
            # 严格择优：等值不覆盖，保留批次号更靠前的既有方案，组合因此确定。
            if _better(candidate, current[w]):
                current[w] = candidate
                kept[i][w] = 1
        previous = current
    chosen = set()
    w = capacity_milli
    for i in range(len(items) - 1, -1, -1):
        if kept[i][w]:
            chosen.add(items[i]['code'])
            w -= items[i]['gas_milli']
    total_gas = sum(item['gas_milli'] for item in items if item['code'] in chosen)
    total_weight = sum(item['weight_units'] for item in items if item['code'] in chosen)
    rejected = [{'code': item['code'], 'reason': '额度不足，未纳入最优装载组合'}
                for item in items if item['code'] not in chosen]
    return chosen, total_gas, total_weight, rejected
