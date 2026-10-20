"""Score the actual integer URL timestamp, not a large returned time span."""

import math


def scene_metrics(question, results, tolerance=10):
    """Return None for non-scene questions so they cannot distort the denominator."""
    if not question.scene_answerable:
        return None
    def hit(result):
        # URLs are generated with floor(cue.start_seconds).
        point=math.floor(result.start_seconds)
        return result.video_id==question.expected_video_id and any(
            start-tolerance<=point<=end+tolerance for start,end in question.accepted_intervals)
    return {'scene_success_at_1':bool(results and hit(results[0])),
            'hit_at_3':any(hit(result) for result in results[:3])}


def answerability_metrics(question, response):
    """Keep abstention/speaker safety separate from scene retrieval performance.

    Day 1 A/B have no intent router: a source-validation `unsupported` result
    cannot count as recognizing an out-of-scope visual request.
    """
    valid = response.status != 'error'
    return {
        'not_found_correct': (valid and response.status == 'not_found' and not response.results)
                             if question.answerability == 'not_found' else None,
        # A/B's constant warning/null field cannot measure speaker-query recognition.
        'speaker_unknown_correct': None,
        'speaker_unknown_reason': 'constant_speaker_warning',
        'unsupported_correct': None,
        'unsupported_reason': ('baseline_has_no_intent_router'
            if question.answerability == 'visual_unsupported' else 'no_applicable_question'),
        'unsupported_speaker_assertions': sum(r.speaker is not None for r in response.results),
    }


def accuracy(values, *, planned=0, reason=None):
    scored = [v for v in values if v is not None]
    return {'correct':sum(scored), 'denominator':len(scored), 'planned_denominator':planned,
            'accuracy':sum(scored)/len(scored) if scored else None,
            'reason': None if scored else (reason or ('not_executed' if planned else 'no_applicable_questions'))}


def summarize(records, tasks):
    """Executed errors stay in applicable denominators; missing work is explicit."""
    from statistics import mean
    summaries = []
    for condition, system in dict.fromkeys((t['condition'], t['system']) for t in tasks):
        group = [r for r in records if (r['condition'],r['system']) == (condition,system)]
        planned = [t for t in tasks if (t['condition'],t['system']) == (condition,system)]
        scenes = [r for r in group if r['metrics'] is not None]
        scene_count = sum(t['question'].scene_answerable for t in planned)
        negatives = sum(t['question'].answerability == 'not_found' for t in planned)
        speakers = sum(t['question'].answerability == 'speaker_unknown' for t in planned)
        visuals = sum(t['question'].answerability == 'visual_unsupported' for t in planned)
        summaries.append({
            'condition':condition, 'system':system, 'planned_questions':len(planned),
            'executed_questions':len(group), 'error_questions':sum(r['status']=='error' for r in group),
            'scene_questions':len(scenes),
            'success_at_1_count':sum(r['metrics']['scene_success_at_1'] for r in scenes),
            'hit_at_3_count':sum(r['metrics']['hit_at_3'] for r in scenes),
            'scene_success_at_1':accuracy([r['metrics']['scene_success_at_1'] for r in scenes], planned=scene_count),
            'hit_at_3':accuracy([r['metrics']['hit_at_3'] for r in scenes], planned=scene_count),
            'not_found_accuracy':accuracy([r['answerability_metrics']['not_found_correct'] for r in group], planned=negatives),
            'speaker_unknown_accuracy':accuracy([], planned=speakers, reason='constant_speaker_warning'),
            'unsupported_accuracy':accuracy([], planned=visuals, reason='baseline_has_no_intent_router'),
            'unsupported_speaker_assertions':sum(r['answerability_metrics']['unsupported_speaker_assertions'] for r in group),
            'mean_seconds':round(mean(r['latency_seconds'] for r in group),4) if group else None,
            'samples_per_question':1,
        })
    return summaries
