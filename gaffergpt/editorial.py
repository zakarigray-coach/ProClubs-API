"""Factual reporter voices with durable rotation and recent-opening exclusion."""
STYLES = {
    'Raine': 'matchday and league recap reporter: energetic and football-focused; results, key moments, momentum, standout players and tactical patterns; critical when Birmingham play poorly',
    'Teagan': 'feature and personality reporter: more storytelling and character, slightly warmer and more conversational; professional and football-focused, never gimmicky',
}
OPENINGS = {
 'Raine': [
  'Birmingham City’s selected fixtures offer the starting point for this week’s review.',
  'This week’s Birmingham City report begins with the results management has chosen to cover.',
  'The latest selected meetings provide another chapter in Birmingham City’s campaign.',
  'Birmingham’s week comes into focus through the fixtures included in this edition.',
  'The recorded results set the scene for a closer look at Birmingham City’s week.',
  'For Birmingham City, this edition brings the selected results together in one account.',
  'The story of Birmingham’s selected match week starts with the verified record.',
  'A review of Birmingham City’s week must begin with what the selected fixtures actually show.',
  'Birmingham City’s latest selected results deserve a measured reading.',
  'The fixtures chosen for this edition frame Birmingham City’s weekly review.',
 ],
 'Teagan': [
  'The games are in the book. Here is what Birmingham’s selected results leave us to discuss.',
  'Time to take stock, Blues: these are the fixtures on this week’s reporting sheet.',
  'Birmingham’s week gets its turn under the spotlight, with the selected results doing the talking.',
  'The scoreboard has had its say. This edition brings Birmingham’s selected fixtures together.',
  'Another edition, another look at the Blues. We start where any proper report should: the results.',
  'No crystal ball required: Birmingham’s selected results give us the facts for this week’s review.',
  'The Blues’ reporting sheet is open. Here is the match week management has selected.',
  'First the results, then the talking points: Birmingham’s selected week is ready for review.',
  'Birmingham’s selected fixtures are on the desk. Let’s get into the football.',
  'The week’s selected games are ready for the sports desk—no dressing up the scorelines needed.',
 ],
}
HEADLINES = {
 'Raine': ['Birmingham’s week in perspective','The Birmingham City weekly review','The selected fixtures, examined','A week in the Blues’ campaign','Birmingham’s results in focus','The record behind the reporting week','Birmingham City: the week accounted for','The Blues’ latest chapter','A measured look at Birmingham’s week','Birmingham’s week on the record'],
 'Teagan': ['The Blues’ week hits the sports desk','Birmingham: scores in, talking points next','The week according to the scoreboard','Blues in the spotlight','Birmingham’s week, straight from the record','The reporting sheet is open','The Blues’ weekly football briefing','Results first. Birmingham’s review follows.','Birmingham’s week gets its column','The Blues’ week: let’s talk football'],
}

def choose_editorial(conn, report_id):
    conn.execute('CREATE TABLE IF NOT EXISTS report_editorial (report_id INTEGER PRIMARY KEY REFERENCES weekly_reports(report_id), reporter TEXT NOT NULL, opening TEXT NOT NULL, style TEXT NOT NULL)')
    existing=conn.execute('SELECT * FROM report_editorial WHERE report_id=?',(report_id,)).fetchone()
    if existing:
        return dict(existing)
    last=conn.execute('SELECT reporter FROM report_editorial ORDER BY rowid DESC LIMIT 1').fetchone()
    reporter='Teagan' if last and last['reporter']=='Raine' else 'Raine'
    recent={row['opening'] for row in conn.execute('SELECT opening FROM report_editorial WHERE reporter=? ORDER BY rowid DESC LIMIT 8',(reporter,))}
    opening=next(line for line in OPENINGS[reporter] if line not in recent)
    conn.execute('INSERT INTO report_editorial VALUES (?,?,?,?)',(report_id,reporter,opening,STYLES[reporter]))
    return {'report_id':report_id,'reporter':reporter,'opening':opening,'style':STYLES[reporter]}

def editorial_headline(editorial, week):
    index=OPENINGS[editorial['reporter']].index(editorial['opening'])
    return HEADLINES[editorial['reporter']][index]+' — '+week[:10]

def editorial_lead(editorial, summary):
    line=editorial['opening']
    if not summary['scored_matches']:
        return line
    total=summary['scored_matches']
    record=f"{summary['wins']} {'win' if summary['wins']==1 else 'wins'}, {summary['draws']} {'draw' if summary['draws']==1 else 'draws'} and {summary['losses']} {'defeat' if summary['losses']==1 else 'defeats'}"
    if editorial['reporter']=='Raine':
        return line+f" Across {total} selected official {'fixture' if total==1 else 'fixtures'} with complete scores, Birmingham recorded {record}, scoring {summary['goals_for']} and conceding {summary['goals_against']}. The results establish the record; they do not, by themselves, establish a tactical cause."
    return line+f" The return: {record} from {total} selected official {'game' if total==1 else 'games'} with complete scores. Birmingham scored {summary['goals_for']} and conceded {summary['goals_against']}. That is the scoreboard accounted for. Explaining the football takes the evidence below."
