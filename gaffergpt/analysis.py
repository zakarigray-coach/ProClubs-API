"""Gaffer supplies measured observations; provider-specific AI can be added here."""
from typing import Protocol


class AnalysisProvider(Protocol):
    def analyze(self, matches: list[dict], statistics: list[dict]) -> dict: ...


class FactualGaffer:
    def analyze(self, matches, statistics):
        official=[m for m in matches if m['match_type']=='Official']
        practice=[m for m in matches if m['match_type']=='Practice']
        metrics={}
        for stat in statistics:
            metrics.setdefault(stat['match_id'],{})[(stat['subject_type'],stat['subject_key'],stat['metric'])]=stat
        comparisons=[]
        ordered=sorted(matches,key=lambda m:(m['played_at'],m['match_id']))
        pairs=[]
        opponents={}
        for match in ordered:
            if match['opponent']:
                opponents.setdefault(match['opponent'].casefold(),[]).append(match)
        for meetings in opponents.values():
            pairs.extend(zip(meetings,meetings[1:]))
        for previous,current in pairs:
            before=metrics.get(previous['match_id'],{}); after=metrics.get(current['match_id'],{})
            for key in before.keys() & after.keys():
                if before[key]['unit']!=after[key]['unit']:
                    continue
                comparisons.append({'from_match':previous['match_id'],'to_match':current['match_id'],
                    'subject_type':key[0],'subject':key[1],'metric':key[2],
                    'before':before[key]['value'],'after':after[key]['value'],'unit':after[key]['unit'],
                    'from_type':previous['match_type'],'to_type':current['match_type']})
        # These are observed changes, not proof of tactical causes or player quality.
        return {'official_ids':[m['match_id'] for m in official],
                'practice_ids':[m['match_id'] for m in practice], 'comparisons':comparisons}
