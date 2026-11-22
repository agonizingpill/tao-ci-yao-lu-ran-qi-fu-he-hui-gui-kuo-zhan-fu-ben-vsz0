"""同配方吨耗横向比对."""

VIEW = (
    '同配方吨耗横向比对',
    '只用单表、累计读数未倒退且覆盖首尾的样本计算吨耗，与同窑、同配方、同版本的上个有效批次对照。',
    ['批次', '窑炉', '配方', '基线版本', '用量 立方米每吨', '可比上批', '上批用量', '变化 立方米每吨', '证据状态'],
    """
WITH meter_sequence AS (
 SELECT g.*, LAG(reading_m3) OVER (PARTITION BY batch_code ORDER BY sampled_at) AS prev_value FROM gas_meter g
), meter_checks AS (
 SELECT batch_code,COUNT(*) AS samples,COUNT(DISTINCT meter_serial) AS meters,MIN(sampled_at) AS first_at,
 MAX(sampled_at) AS last_at,MAX(reading_m3)-MIN(reading_m3) AS consumption,
 BOOL_OR(reading_m3<prev_value) AS reversed FROM meter_sequence GROUP BY batch_code
), normalized AS (
 SELECT b.code,b.kiln,b.recipe,b.baseline_version,b.opened_at,
 CASE WHEN m.samples>=2 AND m.meters=1 AND NOT m.reversed AND m.first_at<=b.opened_at AND m.last_at>=b.closed_at
      THEN ROUND(1000*m.consumption/b.batch_kg,3) END AS per_tonne
 FROM firing_batches b LEFT JOIN meter_checks m ON m.batch_code=b.code
)
SELECT a.code,a.kiln,a.recipe,a.baseline_version,a.per_tonne,prior.code AS previous_batch,prior.per_tonne AS previous_per_tonne,
       a.per_tonne-prior.per_tonne AS shift,
       CASE WHEN a.per_tonne IS NULL THEN '计量未通过吨耗采信'
            WHEN prior.code IS NULL THEN '暂无同窑同配方基线'
            ELSE '具备横向比对条件' END AS evidence_status
FROM normalized a LEFT JOIN LATERAL (
 SELECT b.code,b.per_tonne FROM normalized b WHERE b.kiln=a.kiln AND b.recipe=a.recipe
 AND b.baseline_version=a.baseline_version AND b.per_tonne IS NOT NULL AND (b.opened_at,b.code)<(a.opened_at,a.code)
 ORDER BY b.opened_at DESC,b.code DESC LIMIT 1
) prior ON a.per_tonne IS NOT NULL ORDER BY a.opened_at DESC,a.code
""",
)
