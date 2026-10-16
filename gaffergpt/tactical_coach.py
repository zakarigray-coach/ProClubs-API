"""Club coaching from supplied findings; no invented match statistics or API costs."""
import re
from typing import Protocol


class CoachingProvider(Protocol):
    def advise(self, analysis: str, formation: str = '') -> str: ...


# Each entry separates an observed issue from a tactical change to test.
PLANS = [
    ('Counterattacks', r'counter.?attack|transition|caught.*(?:break|forward)|rest defen',
     'Keep one central midfielder behind the ball and send only one fullback forward at a time. When possession is lost, the nearest player delays the attack while the others recover through the middle.',
     'Play a short scrimmage with a call of “cover” before either fullback advances.',
     'Compare dangerous breaks conceded, using the same PCT measure in the next session.'),
    ('Passing and ball security', r'pass(?:ing|es)?|give.?away|turnover|ball security|los(?:ing|t|s).*ball|possession lost',
     'Give the ball carrier a short option and a forward option. If the forward lane is covered, recycle through midfield instead of forcing it. Avoid sending every attacker on a run at once.',
     'Play a possession drill where the receiver calls the next passing option before receiving.',
     'Compare pass completion and turnovers if PCT supplies them; do not judge passing only by possession.'),
    ('Chance creation', r'chance creat|creat.*chanc|few.*shots|lack.*shots|low.*shots|too few.*shots|stagnant|penetration|sterile|threat|\battack(?:ing)?\b',
     'Keep one wide player stretching the pitch while another attacker checks toward midfield. Use that movement to open a pass into the striker or a run beyond. Recycle when the central lane is crowded.',
     'Rehearse a wide pass, a supporting run and a cutback with attackers arriving at different times.',
     'Compare chances and shots from similar situations; more possession alone does not show better creation.'),
    ('Finishing', r'finish|conversion|wasteful|miss.*(?:chance|shot|sitter)|shooting|shot quality',
     'Prioritize an open shooting lane and balanced body position. If a defender blocks the lane, look for the extra pass rather than forcing the shot. Have a second attacker available for rebounds.',
     'Run a finishing drill where the attacker chooses between shooting and squaring to an open teammate.',
     'Compare shots on target and conversion only if those figures are supplied, alongside chance quality.'),
    ('Pressing', r'press|chasing|compact|disjoint|spacing|shape',
     'Agree one press trigger: a bad touch, a backwards pass or a receiver facing their own goal. The nearest player presses; the next blocks the short pass; midfield protects the center. If support is missing, drop together.',
     'Scrimmage with one player calling “press” or “drop” so the team moves together.',
     'Check whether opponents still play through the first pressure easily; avoid judging the press by tackles alone.'),
    ('Central defending', r'defen|conced|through.?ball|central gap|tackl|back line',
     'Keep a midfielder screening the center and avoid pulling both center backs toward the ball. One defender engages while the other covers depth. Delay the attacker when cover is not ready.',
     'Rehearse defending a striker and a runner with a midfielder recovering to block the central pass.',
     'Compare central chances and shots conceded when available. Fewer goals alone may reflect goalkeeper saves.'),
    ('Wide defending', r'flank|wide.*(?:expos|defen|weak)|wing.*(?:expos|defen)|cross|cutback',
     'Ask the wide midfielder to recover with the opposing fullback. Your fullback delays the winger while a central midfielder protects the cutback lane. Keep a defender covering the central attacker.',
     'Practice defending a winger, overlapping runner and arriving midfielder as a unit.',
     'Check whether the opponent can still reach the byline and find an unmarked cutback.'),
    ('Build-up under pressure', r'build.?up|playing out|pressed|high press|progression',
     'Create a passing triangle around the first receiver. Keep a midfielder available behind the press and a wider outlet. If every short route is closed, use the outlet rather than repeatedly forcing the same central pass.',
     'Start a scrimmage from the keeper with the opposition pressing and rehearse two different exits.',
     'Compare losses in your own third if supplied, and whether you can reach midfield with control.'),
    ('Support and movement', r'isolat|movement|support|run.*behind|off.the.ball',
     'Pair each forward run with a teammate showing for the ball. Keep attackers at different heights instead of all standing on the defensive line. The striker can check short while a wide attacker runs beyond.',
     'Rehearse attacks with one player coming short, one stretching wide and one threatening depth.',
     'Watch whether the ball carrier has two usable options and whether the striker receives with support.'),
    ('Set-piece defending', r'set.?piece|corner|free.?kick',
     'Assign responsibility for the main aerial threat, the near-post space and the edge of the box before the restart. Keep someone ready for the second ball and agree who stays as an outlet.',
     'Repeat several corners with the same assignments, then review any free attackers or second balls.',
     'Compare chances conceded from restarts separately from open-play defending.')
]
PROBLEM = re.compile(r'poor|weak|low|struggl|issue|problem|need|improv|declin|lack|wast|miss|expos|too (?:many|few)|not enough|los(?:t|ing)|conced|vulnerab|fail|bad|leak|stagnant|isolat|disjoint|caught|breakdown|turnover|give.?away|ineffective|inaccurate|sloppy|unable|cannot|can.t', re.I)
NEGATED = re.compile(r'\b(?:no|without)\s+(?:passing|defensive|finishing|pressing|attacking)?\s*(?:issues?|problems?|weaknesses?)\b|\bnot\s+(?:poor|weak|low|wasteful|struggling)\b', re.I)


class PracticalCoach:
    def advise(self, analysis, formation=''):
        analysis=analysis.strip()
        if not analysis or len(analysis)>12000:
            raise ValueError('Paste PCT’s written analysis, up to 12,000 characters.')
        sentences=[s.strip(' -*•\t') for s in re.split(r'[\n.!?]+',analysis) if s.strip()]
        findings=[]
        for title,pattern,change,practice,check in PLANS:
            evidence=next((s for s in sentences if re.search(pattern,s,re.I) and PROBLEM.search(s) and not NEGATED.search(s)),None)
            if evidence:
                findings.append((title,evidence,change,practice,check))
        if not findings:
            return ('PEP — TACTICAL ADVICE\n\nPaste the part of PCT’s written analysis that says what needs fixing. '
                    'For example: “We lose the ball with forced passes and are exposed to counterattacks.” '
                    'A score or stat table alone does not tell me which tactical problem PCT identified. '
                    'Include your formation and what you noticed on the pitch if available.')
        lines=['PEP — TACTICAL ADVICE','Based on the findings you pasted. These are changes to test, not proven causes.']
        if formation.strip():
            lines.append('Your supplied formation: '+formation.strip()[:80])
        for title,evidence,change,practice,check in findings[:3]:
            lines.extend(['',title,'Finding supplied: “'+evidence[:180]+'”',
                          'Try: '+change,'Practice: '+practice,'Check next session: '+check])
        if len(findings)>3:
            lines.append('\nOther areas mentioned: '+', '.join(f[0] for f in findings[3:])+'. Address the first change before adding more.')
        lines.append('\nStart with one change for a short spell. Keep it only if the next session or your observations support it.')
        return '\n'.join(lines)
