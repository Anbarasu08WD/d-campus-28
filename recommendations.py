import os


def _rule_based_advice(metrics, study_hours=2):
    """Always-available fallback advice. This is rule-based, not generative AI."""
    advice = []
    weak = metrics.get('weak_subjects', [])
    if weak:
        for subject in weak[:3]:
            advice.append({
                'title': f"Prioritize {subject['name']}",
                'detail': f"Your current score is {subject['percentage']}%. Schedule a focused {max(20, int(study_hours * 20))}-minute revision session, then solve practice questions.",
                'priority': 'High'
            })
    else:
        advice.append({'title': 'Maintain your subject balance', 'detail': 'No subject is below the demo target of 60%. Continue reviewing each subject weekly.', 'priority': 'Medium'})

    if metrics.get('attendance', 0) < 75:
        advice.append({'title': 'Review attendance', 'detail': f"Your recorded attendance is {metrics.get('attendance', 0)}%. Check your institution's attendance policy and plan to attend upcoming classes.", 'priority': 'High'})
    elif metrics.get('attendance', 0) < 85:
        advice.append({'title': 'Improve attendance consistency', 'detail': 'Your attendance is below the suggested 85% planning target. Track classes attended each week.', 'priority': 'Medium'})

    if metrics.get('assignment_rate', 0) < 80:
        advice.append({'title': 'Close assignment gaps', 'detail': f"Your assignment completion rate is {metrics.get('assignment_rate', 0)}%. Break pending work into short tasks and add due dates in the Study Planner.", 'priority': 'Medium'})
    advice.append({'title': 'Use a realistic routine', 'detail': f"Plan around {study_hours:g} hours of study per day. Split the time into focused blocks and take short breaks between them.", 'priority': 'Low'})
    return advice


def generate_recommendations(metrics, study_hours=2):
    """Hybrid approach: optional OpenAI API enhancement with reliable local fallback.

    Set OPENAI_API_KEY and optionally OPENAI_MODEL to enable generated advice.
    Do not send identifying details; only aggregate academic metrics are sent.
    """
    fallback = _rule_based_advice(metrics, study_hours)
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return {'mode': 'Rule-based fallback', 'items': fallback, 'note': 'AI API is not configured; these recommendations are generated from transparent rules.'}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        compact = {
            'average': metrics.get('average'),
            'attendance': metrics.get('attendance'),
            'assignment_rate': metrics.get('assignment_rate'),
            'subjects': [{'name': s['name'], 'percentage': s['percentage']} for s in metrics.get('subjects', [])],
            'available_study_hours_per_day': study_hours,
        }
        response = client.chat.completions.create(
            model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
            messages=[
                {'role': 'system', 'content': 'You are a careful academic study coach. Use only the supplied aggregate metrics. Do not predict failure or make medical claims. Return 3 to 5 concise, practical study actions. Format each as a short title followed by a detail. Do not claim certainty.'},
                {'role': 'user', 'content': f'Create a practical study plan from these metrics: {compact}'}
            ],
            temperature=0.3,
            max_tokens=350,
        )
        content = response.choices[0].message.content.strip()
        return {'mode': 'AI-assisted', 'items': [{'title': 'AI-generated study plan', 'detail': content, 'priority': 'Personalized'}], 'note': 'AI-generated advice is a suggestion. Review it and follow your institution’s official rules.'}
    except Exception:
        return {'mode': 'Rule-based fallback', 'items': fallback, 'note': 'The AI service was unavailable, so the application used its local recommendation rules.'}
