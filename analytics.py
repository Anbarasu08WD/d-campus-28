def calculate_performance(records):
    """Calculate explainable academic metrics from a list of record dictionaries."""
    total_marks = sum(float(r['marks']) for r in records)
    total_possible = sum(float(r['max_marks']) for r in records)
    average = round((total_marks / total_possible) * 100, 1) if total_possible else 0.0

    attended = sum(int(r['attended_classes']) for r in records)
    classes = sum(int(r['total_classes']) for r in records)
    attendance = round((attended / classes) * 100, 1) if classes else 0.0

    assignments_done = sum(int(r['assignments_completed']) for r in records)
    assignments_total = sum(int(r['assignments_total']) for r in records)
    assignment_rate = round((assignments_done / assignments_total) * 100, 1) if assignments_total else 0.0

    subjects = []
    for record in records:
        maximum = float(record['max_marks']) or 1
        subjects.append({
            'name': record['subject'],
            'marks': float(record['marks']),
            'max_marks': maximum,
            'percentage': round(float(record['marks']) / maximum * 100, 1),
            'attendance': round(int(record['attended_classes']) / int(record['total_classes']) * 100, 1) if int(record['total_classes']) else 0.0,
        })
    subjects.sort(key=lambda item: item['percentage'])
    return {
        'average': average,
        'attendance': attendance,
        'assignment_rate': assignment_rate,
        'assignments_completed': assignments_done,
        'assignments_total': assignments_total,
        'subjects': subjects,
        'weak_subjects': [s for s in subjects if s['percentage'] < 60],
        'subject_count': len(subjects),
    }
