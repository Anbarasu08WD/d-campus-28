import unittest
from analytics import calculate_performance

class AnalyticsTests(unittest.TestCase):
    def test_weighted_average_and_attendance(self):
        records = [
            {'subject': 'Python', 'marks': 80, 'max_marks': 100, 'attended_classes': 8, 'total_classes': 10, 'assignments_completed': 4, 'assignments_total': 5},
            {'subject': 'DBMS', 'marks': 25, 'max_marks': 50, 'attended_classes': 9, 'total_classes': 10, 'assignments_completed': 3, 'assignments_total': 5},
        ]
        result = calculate_performance(records)
        self.assertEqual(result['average'], 70.0)
        self.assertEqual(result['attendance'], 85.0)
        self.assertEqual(result['assignment_rate'], 70.0)
        self.assertEqual(result['weak_subjects'][0]['name'], 'DBMS')

    def test_empty_records(self):
        result = calculate_performance([])
        self.assertEqual(result['average'], 0.0)
        self.assertEqual(result['attendance'], 0.0)
        self.assertEqual(result['subjects'], [])

if __name__ == '__main__':
    unittest.main()
