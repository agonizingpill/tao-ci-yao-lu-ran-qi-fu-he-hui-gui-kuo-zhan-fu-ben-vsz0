"""Business queries over authoritative project records."""

from .operations_reconciliation import RECONCILIATION_VIEWS

from .firing_time_budget import VIEW as FIRING_TIME_BUDGET

from .meter_efficiency import VIEW as METER_EFFICIENCY

from .run_approval_chain import VIEW as RUN_APPROVAL_CHAIN

VIEWS = {
    'meter-provenance': (
        '燃气表跨度审计',
        '按烧成批次比较抄表覆盖起止及燃气表数量，定位缺首尾点或跨表需要补证的记录。',
        ['批次', '窑炉', '抄表点', '燃气表数', '首点', '尾点', '计量核验'],
        """
SELECT b.code,b.kiln,COUNT(g.sampled_at) AS reading_count,COUNT(DISTINCT g.meter_serial) AS meter_count,MIN(g.sampled_at),MAX(g.sampled_at),
       CASE WHEN COUNT(g.sampled_at)<2 THEN '需补起止点' WHEN COUNT(DISTINCT g.meter_serial)>1 THEN '复核跨表计量'
            WHEN MIN(g.sampled_at)>b.opened_at OR MAX(g.sampled_at)<b.closed_at THEN '缺时间边界读数' ELSE '覆盖完整' END
FROM firing_batches b LEFT JOIN gas_meter g ON g.batch_code=b.code GROUP BY b.code ORDER BY b.opened_at DESC,b.code
""",
    ),
    'recipe-evidence': (
        '配方变更证据对照',
        '关联配方变更、回归结果与签认状态，重点标出有变更需求而尚无有效归因的批次。',
        ['批次', '配方', '变更号', '审批状态', '负荷运行号', '归因', '复核状态'],
        """
SELECT b.code,b.recipe,c.id,c.status,r.run_id,r.attribution,
       CASE WHEN r.recipe_change_id IS NULL THEN '等待归因' WHEN r.confirmed_at IS NULL THEN '待主管确认' ELSE '已确认' END
FROM recipe_changes c JOIN firing_batches b ON c.batch_code=b.code LEFT JOIN cycle_reviews r ON r.recipe_change_id=c.id AND r.batch_code=b.code
ORDER BY c.id DESC,b.code
""",
    ),
    **RECONCILIATION_VIEWS,
    'firing-time-budget': FIRING_TIME_BUDGET,
    'meter-efficiency': METER_EFFICIENCY,
    'run-approval-chain': RUN_APPROVAL_CHAIN,
}
