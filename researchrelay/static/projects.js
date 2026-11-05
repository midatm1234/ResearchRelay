'use strict';
const $ = id => document.getElementById(id);
const hub = {status:null,projects:[],repositories:[],repositoryLoaded:false,repositoryPage:0,edit:null,requestId:null,signature:null,busy:false,branchRequest:0};
const operationKey='researchrelay:hub:last-operation';
function el(tag,attrs={},children=[]) {
  const item=document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) {
    if (value==null) continue;
    if (key==='text') item.textContent=String(value);
    else if (key==='class') item.className=value;
    else if (key.startsWith('on')) item.addEventListener(key.slice(2),value);
    else if (key==='value') item.value=value;
    else item.setAttribute(key,String(value));
  }
  for (const child of children) if (child!=null) item.append(child instanceof Node?child:document.createTextNode(String(child)));
  return item;
}
function replace(item,children=[]) {item.replaceChildren(...children);}
function words(value) {return String(value||'').replaceAll('_',' ').replace(/\b\w/g,letter=>letter.toUpperCase());}
function text(value) {return typeof value==='string'?value:value==null?'':Array.isArray(value)?value.join(', '):JSON.stringify(value);}
function slug(value) {return String(value).toLowerCase().replace(/[^a-z0-9-]+/g,'-').replace(/^-+|-+$/g,'').slice(0,70)||'research-project';}
function uniqueId() {return crypto.randomUUID?crypto.randomUUID():`setup-${Date.now()}-${Math.random().toString(36).slice(2)}`;}
function projectURL(project) {return `/projects/${encodeURIComponent(project.id)}`;}
function repositoryURL(name) {return `https://github.com/${String(name||'').split('/').map(encodeURIComponent).join('/')}`;}
let toastTimer;
function toast(message) {$('hub-toast').textContent=message;$('hub-toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('hub-toast').hidden=true;},5000);}
async function api(path,method='GET',payload) {
  const response=await fetch(`/api/hub${path}`,{method,credentials:'same-origin',headers:{Accept:'application/json',...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload)});
  let result;
  try {result=await response.json();} catch {result={detail:'The service did not return project information. Try again.'};}
  if (!response.ok) {
    const error=new Error(typeof result.detail==='string'?result.detail:result.message||`Project request failed (${response.status}).`);
    error.status=response.status;error.payload=result;throw error;
  }
  return result;
}
function showError(destination,error) {
  destination.hidden=false;
  replace(destination,[el('strong',{text:error.message||String(error)})]);
  if (error.payload?.next_action) destination.append(el('p',{text:text(error.payload.next_action)}));
  if ([401,403].includes(error.status)&&!hub.status?.demo) destination.append(el('a',{class:'button secondary',href:hub.status?.github_auth_url||'/api/hub/auth/login',text:'Connect GitHub'}));
  if (error.payload?.operation) {const operation=el('div',{class:'hub-operation'});destination.append(operation);showOperation(error.payload.operation,operation);}
}
async function busy(button,callback) {if(button.disabled)return;button.disabled=true;try{await callback();}catch(error){showError($('hub-error'),error);}finally{button.disabled=false;}}
function accountMessage() {
  const status=hub.status||{};const identity=status.identity;
  $('github-connect').hidden=Boolean(status.demo||!status.configured);
  $('github-connect').href=status.github_auth_url||'/api/hub/auth/login';
  $('github-connect').textContent=identity?'Reconnect GitHub':'Connect GitHub';
  $('hub-identity').textContent=identity?`@${identity.login}`:status.demo?'Choose a demo account':'Not connected';
  $('hub-demo').hidden=!status.demo;
  $('hub-logout').hidden=!identity;
  const message=$('hub-auth');
  if (identity) {message.hidden=true;}
  else {
    message.hidden=Boolean(status.demo);
    replace(message,[el('strong',{text:status.configured?'Connect your GitHub account':'GitHub sign-in is not configured'}),el('p',{text:status.configured?'Sign in to see accessible repositories and projects. Your GitHub permissions govern access; credentials stay with the service.':'Ask the service owner to configure GitHub sign-in. For a credential-free evaluation, start the explicitly labeled local project demo.'})]);
    if (status.configured) message.append(el('a',{href:status.github_auth_url||'/api/hub/auth/login',class:'button primary',text:'Connect GitHub →'}));
  }
}
async function refreshHub() {
  const status=await api('/status');hub.status=status;
  hub.projects=status.projects||[];accountMessage();renderProjects();
  if (sessionStorage.getItem(operationKey)) {$('operation-banner').hidden=false;$('operation-note').textContent=`Setup request ${sessionStorage.getItem(operationKey)}. Check its outcome before repeating creation.`;}
  return status;
}
function renderProjects() {
  const query=$('project-search').value.trim().toLowerCase();
  const projects=hub.projects.filter(project=>[project.name,project.description,project.repository,project.branch].some(value=>String(value||'').toLowerCase().includes(query)));
  $('project-count').textContent=hub.projects.length;
  if (!projects.length) {
    replace($('project-list'),[el('div',{class:'hub-empty'},[el('strong',{text:query?'No matching projects':hub.status?.identity?'Your next collaboration starts here.':'A shared record starts with a connection.'}),el('p',{text:query?'Try another project or repository name.':hub.status?.identity?'Create a project or join an existing project folder on a repository you can access.':'Connect GitHub to create or discover projects. The default workspace remains available separately.'})])]);return;
  }
  replace($('project-list'),projects.map(project=>{
    const problem=el('p',{class:'hub-card-error',role:'status',hidden:'hidden'});
    const status=el('p',{class:'hub-card-sync',text:project.sync?.latest_commit?`Latest retrieved commit: ${project.sync.latest_commit.slice(0,12)}`:project.sync?.status?`Sync: ${words(project.sync.status)}`:'Open or refresh to retrieve current project context.'});
    const refresh=el('button',{type:'button',class:'text-button',text:'Refresh ↻'});
    refresh.addEventListener('click',()=>busy(refresh,async()=>{try{const result=await api(`/projects/${encodeURIComponent(project.id)}/refresh`,'POST',{});Object.assign(project,result.project||{});const sync=result.sync||project.sync||{};status.textContent=sync.latest_commit?`Latest retrieved commit: ${sync.latest_commit.slice(0,12)}`:`Sync: ${words(sync.status||'retrieved')}`;problem.hidden=true;toast('Current project information retrieved.');}catch(error){problem.hidden=false;problem.textContent=[error.message,text(error.payload?.next_action)].filter(Boolean).join(' ');}}));
    const activity=el('button',{type:'button',class:'text-button',text:'Repository activity'});
    activity.addEventListener('click',()=>busy(activity,async()=>{const result=await api(`/projects/${encodeURIComponent(project.id)}/refresh`,'POST',{});showActivity(project,result);}));
    const actions=[el('a',{class:'button primary',href:projectURL(project),text:'Open project →'}),refresh,activity];
    if (!['read','reader'].includes(project.role)) actions.push(el('button',{type:'button',class:'text-button',text:'Edit details',onclick:()=>openForm(project)}));
    const collaborators=Array.isArray(project.collaborators)?project.collaborators:[];
    return el('article',{class:'hub-project-card','data-project-id':project.id},[
      el('div',{class:'hub-card-title'},[el('h3',{},[el('a',{href:projectURL(project),text:project.name||project.id})]),el('span',{class:'status-badge',text:words(project.role||'member')})]),
      el('p',{class:'hub-description',text:project.description||'No description recorded yet.'}),
      el('div',{class:'hub-card-repository'},[hub.status?.demo?el('span',{text:project.repository||'Demo repository'}):el('a',{href:repositoryURL(project.repository),target:'_blank',rel:'noopener',text:project.repository||'Repository pending'})]),
      el('div',{class:'hub-project-meta'},[el('span',{class:'status-badge',text:project.branch||'Branch pending'}),el('span',{text:project.knowledge_path||''}),el('span',{text:collaborators.length?`With ${collaborators.join(', ')}`:'Participant-owned agents'})]),
      project.objectives?el('p',{class:'hub-card-objectives',text:text(project.objectives)}):null,status,problem,el('div',{class:'hub-card-actions'},actions)]);
  }));
}
function showDetail(title,content) {$('hub-detail-title').textContent=title;replace($('hub-detail-content'),content);if(!$('hub-detail-dialog').open)$('hub-detail-dialog').showModal();}
function showActivity(project,result) {
  const commits=result.commits||[];const sync=result.sync||{};
  showDetail(`${project.name||'Project'} · repository activity`,[
    el('p',{class:'hub-help',text:`${project.repository} · ${project.branch}. ${sync.latest_commit?`Retrieved ${sync.latest_commit.slice(0,12)}.`:''}`}),
    ...(!commits.length?[el('p',{class:'hub-help',text:'No recent commits were returned. Open the repository to inspect its history.'})]:commits.map(commit=>el('article',{class:'hub-activity-item'},[
      el('strong',{text:commit.commit?.message||commit.message||commit.sha?.slice(0,12)||'Repository update'}),
      el('small',{text:[commit.sha?.slice(0,12),commit.commit?.author?.name||commit.author?.login||(typeof commit.author==='string'?commit.author:''),commit.commit?.author?.date||commit.committed_at].filter(Boolean).join(' · ')}),
      commit.sha&&!hub.status?.demo?el('a',{class:'hub-github-link',href:`${repositoryURL(project.repository)}/commit/${encodeURIComponent(commit.sha)}`,target:'_blank',rel:'noopener',text:'View commit ↗'}):null])))]);
}
function operationText(operation) {return `${words(operation.status||'pending')} · ${words(operation.phase||'project setup')}${operation.id?` · ${operation.id}`:''}`;}
function showOperation(operation,destination=$('project-form-operation'),project=null) {
  if (!operation) return;
  replace(destination,[el('p',{text:operationText(operation)})]);
  if (operation.next_action||operation.recovery) destination.append(el('p',{text:text(operation.next_action||operation.recovery)}));
  if (project?.id) destination.append(el('a',{class:'button primary',href:projectURL(project),text:'Open project →'}));
  const request=operation.request_id||hub.requestId||operation.id;
  if (request) {sessionStorage.setItem(operationKey,request);$('operation-banner').hidden=false;$('operation-note').textContent=operationText(operation);}
}
async function recoverOperation() {
  const requestId=sessionStorage.getItem(operationKey);if(!requestId)return;
  const result=await api(`/operations/${encodeURIComponent(requestId)}`);const operation=result.operation||result;
  const children=[el('p',{class:'hub-help',text:operationText(operation)})];
  if (operation.next_action||operation.recovery) children.push(el('p',{class:'hub-help',text:text(operation.next_action||operation.recovery)}));
  const project=result.project||operation.project;
  if (project?.id) children.push(el('a',{class:'button primary',href:projectURL(project),text:'Open project →'}));
  if (operation.status!=='completed'&&operation.state!=='needs_reconciliation'&&operation.status!=='needs_reconciliation'&&operation.original_input) {
    const problem=el('div',{class:'hub-error',hidden:'hidden',role:'alert'});
    const resume=el('button',{class:'button primary',type:'button',text:'Resume setup'});
    resume.addEventListener('click',()=>busy(resume,async()=>{
      try {const result=await api(`/operations/${encodeURIComponent(requestId)}/resume`,'POST',{});showOperation(result.operation,$('hub-detail-content'),result.project);await refreshHub();}
      catch(error){showError(problem,error);}
    }));
    children.push(el('p',{class:'hub-help',text:'Resume uses the original saved setup request. It does not change the repository, branch, visibility, or project scope.'}),resume,problem);
  }
  showDetail('Project setup status',children);await refreshHub();
}
async function loadRepositories(more=false) {
  if (!hub.status?.identity) return;
  const page=more?hub.repositoryPage+1:1;const result=await api(`/repositories?page=${page}`);const repositories=result.repositories||[];
  hub.repositories=more?[...hub.repositories,...repositories]:repositories;hub.repositoryPage=page;hub.repositoryLoaded=true;$('more-repositories').hidden=repositories.length<100;renderRepositories();
}
function renderRepositories() {
  const selection=$('existing-repository').value;const mode=currentMode();
  replace($('existing-repository'),[el('option',{value:'',text:'Select a repository…'}),...hub.repositories.map(repository=>{
    const option=el('option',{value:repository.full_name,text:`${repository.full_name}${repository.private?' · private':''}${repository.permissions?.push===false?' · read only':''}`});
    option.disabled=mode==='new_branch'&&repository.permissions?.push===false;return option;
  })]);
  if (hub.repositories.some(repository=>repository.full_name===selection)) $('existing-repository').value=selection;
  $('repository-help').textContent=hub.repositories.length?'Repositories available to your connected account. Organization policies and branch protections still apply.':'No accessible repositories were returned. Check repository access or reconnect GitHub.';
}
async function loadBranches() {
  const repository=$('existing-repository').value;const request=++hub.branchRequest;
  for(const id of ['base-branch','connect-branch']) replace($(id),[el('option',{value:'',text:repository?'Retrieving branches…':'Select a repository first…'})]);
  if(!repository)return;
  try {
    const result=await api(`/repositories/${repository.split('/').map(encodeURIComponent).join('/')}/branches`);
    if (request!==hub.branchRequest||repository!==$('existing-repository').value)return;
    const branches=result.branches||[];
    for(const id of ['base-branch','connect-branch']) replace($(id),branches.length?branches.map(branch=>el('option',{value:branch.name,text:branch.name})):[el('option',{value:'',text:'No branches available'})]);
    const defaultBranch=hub.repositories.find(item=>item.full_name===repository)?.default_branch;
    if(branches.some(branch=>branch.name===defaultBranch))for(const id of ['base-branch','connect-branch'])$(id).value=defaultBranch;
  } catch(error) {showError($('project-form-error'),error);}
}
function currentMode(){return document.querySelector('input[name="mode"]:checked').value;}
function setGroup(id,visible){$(id).hidden=!visible;$(id).querySelectorAll('input,select,textarea,button').forEach(control=>{control.disabled=!visible;});}
function updateMode() {
  const mode=currentMode();const editing=Boolean(hub.edit);const joining=mode==='connect'&&!$('initialize-project').checked&&!editing;
  setGroup('new-repository-fields',!editing&&mode==='new_repository');setGroup('existing-repository-fields',!editing&&mode!=='new_repository');
  setGroup('base-branch-field',!editing&&mode==='new_branch');setGroup('connect-branch-field',!editing&&mode==='connect');
  setGroup('new-branch-field',!editing&&mode!=='connect');setGroup('initialize-field',!editing&&mode==='connect');
  $('repository-mode').hidden=editing;$('repository-mode').disabled=editing;
  $('project-details').hidden=joining;$('project-details').disabled=joining;
  $('advanced-settings').hidden=editing;$('knowledge-path').disabled=editing;$('knowledge-path').required=joining;
  if(joining)$('advanced-settings').open=true;
  $('submit-project').textContent=editing?'Save project details →':joining?'Join project →':'Create project →';
  $('branch-help').textContent=mode==='new_repository'?'The initial branch for your new repository.':'A new branch, starting from the selected base. Existing branches will not be overwritten.';
  $('submit-project').disabled=!hub.status?.identity||hub.busy;
  if(!editing&&mode!=='new_repository') {if(hub.repositoryLoaded)renderRepositories();else loadRepositories().catch(error=>showError($('project-form-error'),error));}
}
function openForm(project=null) {
  hub.edit=project;$('submit-project').hidden=false;hub.requestId=null;hub.signature=null;$('project-form').reset();$('project-dialog-title').textContent=project?'Edit project details':'New Project';
  $('project-name').value=project?.name||'';$('project-description').value=project?.description||'';$('project-objectives').value=text(project?.objectives||'');$('project-collaborators').value=(project?.collaborators||[]).join(', ');
  $('repository-owner').value=hub.status?.identity?.login||'';
  $('project-form-error').hidden=true;replace($('project-form-operation'));
  $('form-intro').textContent=hub.status?.identity?project?'Update the shared project description and collaborators. Repository access still follows GitHub permissions.':'Your GitHub permissions determine where this project can be created. A new repository is private by default.':'Connect GitHub before creating or joining a project. Your account credentials stay with the service.';
  updateMode();$('project-dialog').showModal();
}
$('project-name').addEventListener('input',()=>{if(hub.edit)return;if(!$('repository-name').dataset.edited)$('repository-name').value=slug($('project-name').value);if(!$('project-branch').dataset.edited)$('project-branch').value=currentMode()==='new_branch'?`researchrelay/${slug($('project-name').value)}`:'main';});
$('repository-name').addEventListener('input',()=>{$('repository-name').dataset.edited='true';});
$('project-branch').addEventListener('input',()=>{$('project-branch').dataset.edited='true';});
document.querySelectorAll('input[name="mode"]').forEach(input=>input.addEventListener('change',()=>{if(!$('project-branch').dataset.edited)$('project-branch').value=currentMode()==='new_branch'?`researchrelay/${slug($('project-name').value)}`:'main';updateMode();}));
$('initialize-project').addEventListener('change',updateMode);$('existing-repository').addEventListener('change',()=>loadBranches());
$('reload-repositories').addEventListener('click',event=>busy(event.currentTarget,async()=>{try{await loadRepositories();}catch(error){showError($('project-form-error'),error);}}));
$('more-repositories').addEventListener('click',event=>busy(event.currentTarget,async()=>{try{await loadRepositories(true);}catch(error){showError($('project-form-error'),error);}}));
$('project-form').addEventListener('submit',async event=>{
  event.preventDefault();if(hub.busy||!hub.status?.identity)return;hub.busy=true;updateMode();$('project-form-error').hidden=true;
  try {
    const metadata={name:$('project-name').value.trim(),description:$('project-description').value.trim(),objectives:$('project-objectives').value.trim(),collaborators:$('project-collaborators').value.split(/[\s,]+/).map(value=>value.replace(/^@/,'').trim()).filter(Boolean)};
    if(hub.edit) {await api(`/projects/${encodeURIComponent(hub.edit.id)}`,'PATCH',metadata);$('project-dialog').close();await refreshHub();toast('Project details updated.');return;}
    const mode=currentMode();const joining=mode==='connect'&&!$('initialize-project').checked;
    const payload=joining?{repository:$('existing-repository').value,branch:$('connect-branch').value,knowledge_path:$('knowledge-path').value.trim()}:{...metadata,mode,repository:mode==='new_repository'?`${$('repository-owner').value.trim()}/${$('repository-name').value.trim()}`:$('existing-repository').value,branch:mode==='connect'?$('connect-branch').value:$('project-branch').value.trim(),...(mode==='new_branch'?{base_branch:$('base-branch').value}:{}),visibility:$('repository-visibility').value,initialize:true,...($('knowledge-path').value.trim()?{knowledge_path:$('knowledge-path').value.trim()}:{})};
    if(!payload.repository||!payload.branch)throw new Error('Select a repository and branch before continuing.');
    if(joining) {const result=await api('/projects/join','POST',payload);$('project-dialog').close();await refreshHub();toast('Existing project joined.');if(result.project?.id)showDetail('Project ready',[el('a',{class:'button primary',href:projectURL(result.project),text:'Open project →'})]);return;}
    const signature=JSON.stringify(payload);if(signature!==hub.signature){hub.signature=signature;hub.requestId=uniqueId();}payload.request_id=hub.requestId;
    sessionStorage.setItem(operationKey,hub.requestId);$('project-form-operation').textContent='Creating the shared project record. You can recover this setup by its request ID if the connection is interrupted.';
    const result=await api('/projects','POST',payload);showOperation(result.operation,$('project-form-operation'),result.project);await refreshHub();
    if(result.project?.id) {toast('Project is ready. Open it to agree on tasks and connect your agents.');$('submit-project').hidden=true;}
  } catch(error) {showError($('project-form-error'),error);}
  finally {hub.busy=false;updateMode();}
});
$('new-project').addEventListener('click',()=>{$('submit-project').hidden=false;delete $('repository-name').dataset.edited;delete $('project-branch').dataset.edited;openForm();});
$('cancel-project-form').addEventListener('click',()=>{$('project-dialog').close();});$('close-project-dialog').addEventListener('click',()=>{$('project-dialog').close();});
$('close-hub-detail').addEventListener('click',()=>{$('hub-detail-dialog').close();});
$('hub-logout').addEventListener('click',event=>busy(event.currentTarget,async()=>{await api('/auth/logout','POST',{});hub.repositories=[];hub.repositoryLoaded=false;sessionStorage.removeItem(operationKey);$('operation-banner').hidden=true;await refreshHub();toast('Signed out.');}));
$('hub-refresh').addEventListener('click',event=>busy(event.currentTarget,refreshHub));$('project-search').addEventListener('input',renderProjects);
$('recover-operation').addEventListener('click',event=>busy(event.currentTarget,recoverOperation));
document.querySelectorAll('[data-demo-login]').forEach(button=>button.addEventListener('click',()=>busy(button,async()=>{await api('/auth/demo','POST',{login:button.dataset.demoLogin});hub.repositoryLoaded=false;await refreshHub();toast(`Local demonstration account: ${button.dataset.demoLogin}.`);} )));
refreshHub().then(()=>{const query=new URLSearchParams(location.search);if(query.get('auth_error'))showError($('hub-error'),new Error(query.get('auth_error')));if(query.get('new')==='1')$('new-project').click();}).catch(error=>showError($('hub-error'),error));
