import hashlib
from datetime import datetime

import numpy as np
from sklearn.linear_model import ElasticNetCV
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import KFold, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 1073
FEATURES = ['batch_kg', 'ramp_hours', 'soak_hours', 'cool_hours', 'ramp_peak_c', 'soak_peak_c', 'cool_peak_c']


def duration_hours(start, end):
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 3600


def historical_batches():
    rng = np.random.default_rng(SEED)
    mass = rng.uniform(700, 1600, 160)
    ramp = rng.uniform(1.5, 4.5, 160)
    soak = rng.uniform(.6, 2.8, 160)
    cool = rng.uniform(1, 4, 160)
    ramp_peak = rng.uniform(840, 1120, 160)
    soak_peak = ramp_peak + rng.uniform(40, 165, 160)
    cool_peak = soak_peak - rng.uniform(60, 220, 160)
    x = np.column_stack((mass, ramp, soak, cool, ramp_peak, soak_peak, cool_peak))
    target_m3 = (24 + .014 * mass + 11 * ramp + 16 * soak + 3.5 * cool +
                 .035 * ramp_peak + .025 * soak_peak + rng.normal(0, 2.4, len(mass)))
    return x, target_m3


def fit_model():
    """在固定合成历史窑次上拟合标准化 ElasticNet，返回模型与留出集度量。"""
    x, y = historical_batches()
    train_x, test_x, train_y, test_y = train_test_split(x, y, test_size=.25, random_state=SEED)
    cv = KFold(5, shuffle=True, random_state=SEED)
    model = make_pipeline(StandardScaler(), ElasticNetCV(l1_ratio=[.15, .5, .85, 1.0],
                          alphas=np.logspace(-3, 1, 40), cv=cv, max_iter=10000, random_state=SEED))
    model.fit(train_x, train_y)
    metrics = {'mae_m3': round(float(mean_absolute_error(test_y, model.predict(test_x))), 3),
               'train_count': len(train_y), 'holdout_count': len(test_y),
               'training_sha256': hashlib.sha256(np.column_stack((x, y)).astype('<f8').tobytes()).hexdigest()}
    return model, metrics


def predict_features(model, features):
    return round(float(model.predict([features])[0]), 3)


def measured_features(snapshot):
    """已登记温区的窑次：阶段时长取区间端点之差，峰值取温区登记值。"""
    curves = snapshot['curve']
    features = [float(snapshot['cycle']['batch_kg'])]
    features += [duration_hours(c['started_at'], c['ended_at']) for c in curves]
    features += [float(c['peak_c']) for c in curves]
    return features


def plan_features(batch_kg, planned_minutes, program):
    """计划口径：按温程比例拆分计划节拍，峰值取配方计划温程。"""
    total_hours = float(planned_minutes) / 60
    return [float(batch_kg),
            total_hours * float(program['ramp_share']),
            total_hours * float(program['soak_share']),
            total_hours * (1 - float(program['ramp_share']) - float(program['soak_share'])),
            float(program['ramp_peak_c']), float(program['soak_peak_c']), float(program['cool_peak_c'])]


def estimate(snapshot):
    curves, meter = snapshot['curve'], snapshot['meter']
    model, metrics = fit_model()
    fitted = model.named_steps['elasticnetcv']
    features = measured_features(snapshot)
    prediction = predict_features(model, features)
    actual = round(float(meter[-1]['reading_m3']) - float(meter['0']['reading_m3']), 3)
    return {'expected_m3': prediction, 'actual_m3': actual, 'delta_m3': round(actual - prediction, 3),
            **metrics, 'seed': SEED, 'cv_folds': 5, 'alpha': float(fitted.alpha_),
            'l1_ratio': float(fitted.l1_ratio_),
            'features': dict(zip(FEATURES, features)), 'coefs_scaled': dict(zip(FEATURES, map(float, fitted.coef_)))}
