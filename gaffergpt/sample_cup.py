"""Create a clearly labelled private demonstration in a disposable database."""
import json
import tempfile
from pathlib import Path
from .database import Database
from .competitions import configure_report,set_match_details,snapshot
from .report_verification import build_fact_sheet,validate_final
from .cup_cover import render_pages


def create_sample(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        db=Database(Path(folder)/'sample-only.db');key='mpl-pre-season-cup-2026'
        report=db.open_report('2026-10-13T04:00:00+00:00','2026-10-16T04:00:00+00:00','SAMPLE',key)
        configure_report(db,report['report_id'],key,'Eliminated','FICTIONAL TEST DATA: semifinal lost 1-2.')
        ids=[]
        for index,(opponent,own,other,stage,day) in enumerate([('Test Albion',2,1,'Quarter-final',13),('Test Rovers',1,2,'Semi-final',15)]):
            mid=db.ingest(str(index),'SAMPLE','SAMPLE',f'2026-10-{day}T23:00:00+00:00','FICTIONAL TEST DATA',
                [{'opponent':opponent,'birmingham_score':own,'opponent_score':other}])[0]
            set_match_details(db,mid,key,'SAMPLE','FICTIONAL TEST DATA',stage=stage)
            db.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value,source) VALUES (?,'player','Sample Forward','goals',1,'fictional test fixture')",(mid,))
            ids.append(mid)
        db.replace_page_selection(report['report_id'],ids,ids)
        packet={'matches':db.selected(report['report_id']),'statistics':db.rows('SELECT * FROM match_statistics'),
                'competition_context':snapshot(db,report['report_id']),
                'management':{'player_name':'Sample Forward','player_evidence':'FICTIONAL TEST DATA: selected Cup Standout.'}}
        sheet=build_fact_sheet(packet)
        title='Birmingham’s cup run ends on fine margins'
        paragraphs=[
            'Sample Forward’s two goals stood out as Birmingham City were eliminated from The Minglewood Cup at the semi-final stage.',
            'Birmingham beat Test Albion 2–1 in the quarter-final. A 1–2 defeat against Test Rovers in the semi-final ended their involvement in The Minglewood Cup.',
            'Across their cup fixtures, Birmingham scored three goals and conceded three. The contrasting results left little between a place in the next round and the end of the run.',
            'Sample Forward was the club’s Cup Standout. The recognition offered an individual bright spot, but Birmingham finished with a narrow defeat to set beside their narrow victory. The difference between those outcomes was small; its consequence in a knockout competition was decisive.'
        ]
        body='\n\n'.join(paragraphs)
        claims=[]
        targets=[('player','goals','Sample Forward',paragraphs[0]),('event','confirmed_outcome','The Minglewood Cup',paragraphs[0]),
            ('fixture','score','Test Albion',paragraphs[1].split('. ')[0]+'.'),('fixture','score','Test Rovers','A '+paragraphs[1].split('. A ')[1]),
            ('team','goals_for','Birmingham City',paragraphs[2]),('team','goals_against','Birmingham City',paragraphs[2]),('award','cup_standout','Sample Forward',paragraphs[3])]
        for kind,metric,subject,quote in targets:
            fact_id=next(k for k,f in sheet['facts'].items() if f['kind']==kind and f['metric']==metric and f['subject']==subject)
            claims.append({'fact_id':fact_id,'quote':quote})
        # Progression must use the exact confirmed outcome; use a clear statement in this demonstration.
        paragraphs[0]=paragraphs[0].replace('ended with elimination','ended with Birmingham eliminated')
        body='\n\n'.join(paragraphs)
        for claim in claims:claim['quote']=claim['quote'].replace('ended with elimination','ended with Birmingham eliminated')
        proof=validate_final({'title':title,'body':body},sheet,{'claims':claims,'unsupported':[]})
        (destination/'RT_Cup_Sample.txt').write_text('SAMPLE — FICTIONAL TEST RESULTS, NOT A REAL CUP REPORT\nRT FOOTBALL MEDIA\n'+title+'\n\n'+body+'\n\nThis demonstration was checked locally against isolated test data. It has not been publicly posted.\n')
        (destination/'sample-checks.json').write_text(json.dumps({'facts':sheet,'validation':proof},indent=2))
        for i,data in enumerate(render_pages(packet['competition_context']['event'],title,'Sample Forward',sample=True)):
            (destination/f'RT_Cup_Sample_{i+1}.png').write_bytes(data)
        return proof


if __name__=='__main__':
    import sys
    print(json.dumps(create_sample(sys.argv[1]),indent=2))
