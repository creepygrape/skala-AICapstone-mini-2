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
