"""Additional operational reconciliation rules for this project."""

RECONCILIATION_VIEWS = {
    'thermal-phase-handoff': (
        '窑炉热段交接完整性',
        '按应有的升温、保温、冷却顺序核对时间边界和来源文件，为班组定位漏段、重叠和间隙。',
        ['烧成批次', '窑炉', '阶段', '开始', '结束', '上一阶段结束', '曲线文件', '交接结论'],
        """
WITH stages(phase,position) AS (VALUES ('ramp',1),('soak',2),('cool',3))
SELECT b.code,b.kiln,s.phase,c.started_at,c.ended_at,previous.ended_at AS previous_stage_ended_at,c.source_file,
       CASE WHEN c.phase IS NULL THEN '待补温度曲线'
            WHEN s.position=1 AND c.started_at<>b.opened_at THEN '首段与开炉时间不齐'
            WHEN s.position>1 AND previous.phase IS NULL THEN '待补上一阶段'
            WHEN c.started_at<previous.ended_at THEN '阶段重叠'
            WHEN c.started_at>previous.ended_at THEN '交接存在间隙'
            WHEN s.position=3 AND c.ended_at<>b.closed_at THEN '末段与关炉时间不齐'
            ELSE '交接连续' END
FROM firing_batches b CROSS JOIN stages s
LEFT JOIN kiln_curve c ON c.batch_code=b.code AND c.phase=s.phase
LEFT JOIN stages predecessor ON predecessor.position=s.position-1
LEFT JOIN kiln_curve previous ON previous.batch_code=b.code AND previous.phase=predecessor.phase
ORDER BY b.opened_at DESC,b.code,s.position
""",
    ),
}
