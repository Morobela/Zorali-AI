from app.reality.project_scanner import status_report

def test_status_report_current():
    data = status_report('.')
    assert 'status_report' in data
