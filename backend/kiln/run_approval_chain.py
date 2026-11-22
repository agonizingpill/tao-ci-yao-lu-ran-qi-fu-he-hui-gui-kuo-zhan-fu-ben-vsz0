"""燃气估算复核版本锁定."""

VIEW = (
    '燃气估算复核版本锁定',
    '并排显示班组已引用的估算、本批最新有效估算和最新获批配方版本，定位有新证据但仍沿用旧估算的复核。',
    ['批次', '锁定基线', '最新获批配方版本', '复核引用估算', '最新有效估算', '主管', '跟进建议'],
    """
SELECT b.code,b.baseline_version,v.version AS latest_approved_recipe,r.run_id AS signed_run,
       model.id AS newest_run,r.confirmed_by,
       CASE WHEN model.id IS NULL THEN '待取得有效估算'
            WHEN r.run_id IS NULL THEN '未关联估算复核'
            WHEN r.run_id<>model.id THEN '新估算未纳入复核'
            WHEN v.id IS NOT NULL AND r.recipe_change_id IS DISTINCT FROM v.id AND r.attribution='recipe'
                 THEN '配方归因版本需对照'
            WHEN r.confirmed_by IS NULL THEN '等待独立复核'
            ELSE '已锁定复核版本' END AS review_status
FROM firing_batches b LEFT JOIN cycle_reviews r ON r.batch_code=b.code
LEFT JOIN LATERAL (SELECT id,version FROM recipe_changes WHERE batch_code=b.code AND status='approved'
                   ORDER BY version DESC,id DESC LIMIT 1) v ON TRUE
LEFT JOIN LATERAL (SELECT id FROM load_runs WHERE batch_code=b.code AND status='ready' ORDER BY id DESC LIMIT 1) model ON TRUE
ORDER BY b.opened_at DESC,b.code
""",
)
