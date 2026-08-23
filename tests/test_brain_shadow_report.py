from core.brain_shadow_report import build_shadow_evaluation_report


def test_report_requires_minimum_sample_before_eligibility():
    rows = [
        {"winner": "AI", "ai_return_percent": 2.0, "deterministic_return_percent": 1.0}
    ]
    report = build_shadow_evaluation_report(rows, min_sample_size=2)
    assert report.sample_size == 1
    assert report.eligible is False
    assert report.ai_wins == 1


def test_report_calculates_performance_metrics():
    rows = [
        {"winner": "AI", "ai_return_percent": 2.0, "deterministic_return_percent": -1.0},
        {"winner": "DETERMINISTIC", "ai_return_percent": -2.0, "deterministic_return_percent": 1.0},
        {"winner": "TIE", "ai_return_percent": 0.5, "deterministic_return_percent": 0.5},
    ]
    report = build_shadow_evaluation_report(rows, min_sample_size=3)
    assert report.eligible is True
    assert report.sample_size == 3
    assert report.ai_win_rate == 2 / 3
    assert report.deterministic_win_rate == 2 / 3
    assert report.ai_average_return_percent == 0.16666666666666666
    assert report.deterministic_average_return_percent == 0.16666666666666666
    assert report.ai_wins == 1
    assert report.deterministic_wins == 1
    assert report.ties == 1


def test_empty_report_is_not_eligible():
    report = build_shadow_evaluation_report([], min_sample_size=1)
    assert report.sample_size == 0
    assert report.eligible is False
