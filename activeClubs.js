// CrownFC remains in historical stores, but no longer runs live workflows.
const ACTIVE_TEAM_KEYS=Object.freeze(['birmingham']);
const isActiveClub=key=>ACTIVE_TEAM_KEYS.includes(key);
const RETIRED_COMMANDS=new Set(['import-mlpc-schedule','setup-server','streamline-server']);
function activeCommands(commands){
  return commands.filter(command=>!RETIRED_COMMANDS.has(command.name)).map(command=>{
    const result=JSON.parse(JSON.stringify(command));
    for(const option of result.options || [])if(option.name==='club' && option.choices)option.choices=option.choices.filter(choice=>isActiveClub(choice.value));
    return result;
  });
}
module.exports={ACTIVE_TEAM_KEYS,isActiveClub,activeCommands,RETIRED_COMMANDS};
