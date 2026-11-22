"""烧成时长预算分解."""

VIEW = (
    '烧成时长预算分解',
    '按完整批次拆分升温、保温、冷却和曲线外时间，呈现与计划对比。资料缺段时不将差值认作真实空档。',
    ['批次', '计划 分钟', '开关炉 分钟', '升温 分钟', '保温 分钟', '冷却 分钟', '曲线外 分钟', '计划偏差 分钟', '核对结论'],
    """
WITH phase_stats AS (
 SELECT batch_code,COUNT(*) AS phases,
 SUM(EXTRACT(EPOCH FROM (ended_at-started_at))/60) AS covered,
 MAX(EXTRACT(EPOCH FROM (ended_at-started_at))/60) FILTER (WHERE phase='ramp') AS ramp,
 MAX(EXTRACT(EPOCH FROM (ended_at-started_at))/60) FILTER (WHERE phase='soak') AS soak,
 MAX(EXTRACT(EPOCH FROM (ended_at-started_at))/60) FILTER (WHERE phase='cool') AS cool
 FROM kiln_curve GROUP BY batch_code
), durations AS (
 SELECT b.code,b.planned_minutes,p.phases,p.covered,p.ramp,p.soak,p.cool,
 EXTRACT(EPOCH FROM (b.closed_at-b.opened_at))/60 AS elapsed FROM firing_batches b LEFT JOIN phase_stats p ON p.batch_code=b.code
)
SELECT code,planned_minutes,ROUND(elapsed,1) AS elapsed_minutes,ROUND(ramp,1) AS ramp_minutes,
       ROUND(soak,1) AS soak_minutes,ROUND(cool,1) AS cool_minutes,
       CASE WHEN phases=3 THEN ROUND(elapsed-covered,1) END AS outside_minutes,ROUND(elapsed-planned_minutes,1) AS deviation,
       CASE WHEN COALESCE(phases,0)<>3 THEN '资料缺段'
            WHEN covered>elapsed THEN '阶段跨度超出批次，复核边界'
            WHEN elapsed>planned_minutes THEN '实际时长超计划'
            ELSE '实际时长在计划内' END AS assessment
FROM durations ORDER BY ABS(elapsed-planned_minutes) DESC,code
""",
)
