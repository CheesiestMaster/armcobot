#! /usr/bin/env python3
# Minimal web server companion tool - no new deps, single file
# Uses existing aiohttp dependency and bundles HTML inline

import aiohttp
from aiohttp import web
import sys
import os
import json
import atexit
import signal
import logging
import base64
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from models import BaseModel

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment
load_dotenv("sensitive.env")

# Database setup
engine = create_engine(
    url=str(os.getenv("DATABASE_URL")),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)
Session = sessionmaker(bind=engine)

# Global session for identity map persistence
global_session = None

# Authentication credentials
auth_credentials = []

def get_global_session():
    """Get or create the global session"""
    global global_session
    if global_session is None:
        global_session = Session()
        logger.info("Created global session")
    return global_session

def make_json_serializable(value):
    """Convert non-JSON-serializable values to serializable ones"""
    if value is None:
        return None
    elif isinstance(value, set):
        return list(value)
    elif hasattr(value, 'value'):  # It's an Enum
        return value.value
    elif isinstance(value, (list, tuple)):
        return [make_json_serializable(item) for item in value]
    elif isinstance(value, dict):
        return {k: make_json_serializable(v) for k, v in value.items()}
    else:
        return value

async def check_auth(request):
    """Check basic authentication if credentials are configured"""
    if not auth_credentials:
        return True  # No auth required
    
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Basic '):
        return False
    
    try:
        # Decode the base64 credentials
        encoded_credentials = auth_header[6:]  # Remove 'Basic '
        decoded_credentials = base64.b64decode(encoded_credentials).decode('utf-8')
        username, password = decoded_credentials.split(':', 1)
        
        # Check if this credential pair is in our list
        return (username, password) in auth_credentials
    except Exception as e:
        logger.warning(f"Auth error: {e}")
        return False

@web.middleware
async def auth_middleware(request, handler):
    """Middleware to check authentication for all routes"""
    if not await check_auth(request):
        return web.Response(text='Unauthorized', status=401, headers={'WWW-Authenticate': 'Basic realm="WebEditor"'})
    return await handler(request)

# Minimal HTML for the companion tool
index_html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>SQLA Data Graph Editor (CDN, /api/* only)</title>

<!-- CDNs (no local static beyond / and /favicon.ico) -->
<script src="https://cdn.jsdelivr.net/npm/cytoscape@3.28.1/dist/cytoscape.min.js" crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js" crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js" crossorigin="anonymous"></script>

<style>
  :root { --bg:#0f1220; --panel:#151a33; --ink:#eaf0ff; --muted:#96a1b7; --accent:#6cc; --accent2:#c6f; --danger:#ff6b6b; }
  html,body { height:100%; margin:0; font:14px/1.45 system-ui, -apple-system, Segoe UI, Roboto, Arial; background:var(--bg); color:var(--ink); }
  #app { position:fixed; inset:0; display:grid; grid-template-columns: 1fr 320px; grid-template-rows: auto 1fr auto; grid-template-areas:
      "toolbar toolbar"
      "graph   inspector"
      "status  inspector"; }
  .toolbar { grid-area:toolbar; display:flex; gap:8px; align-items:center; padding:10px; border-bottom:1px solid #262a48;
    background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(0,0,0,.1)); backdrop-filter:blur(6px); }
  .toolbar button,.toolbar input,.toolbar select { background:var(--panel); color:var(--ink); border:1px solid #2a2f4a; border-radius:10px; padding:7px 10px; }
  .toolbar button[data-active="true"]{ outline:2px solid var(--accent); }
  .toolbar .spacer{flex:1}
  #cy { grid-area:graph; height:100%; width:100%; }
  .inspector { grid-area:inspector; border-left:1px solid #262a48; background:#0f142e; display:flex; flex-direction:column; }
  .inspector h3 { margin:12px 12px 6px; font-size:13px; color:#cfd6ff; letter-spacing:.02em; }
  .inspector .section { padding:10px 12px; border-top:1px solid #20264a; }
  .inspector .kv { display:grid; grid-template-columns: 110px 1fr; gap:8px; align-items:center; margin:4px 0; }
  .inspector input, .inspector textarea, .inspector select { width:100%; background:#12173a; color:var(--ink); border:1px solid #2a2f4a; border-radius:8px; padding:6px 8px; }
  .inspector .btnrow { display:flex; gap:8px; margin-top:8px; }
  .status { grid-area:status; padding:8px 10px; color:var(--muted); border-top:1px solid #262a48; background:rgba(0,0,0,.2); }
  .pill { display:inline-block; padding:2px 6px; border:1px solid #3b4272; border-radius:999px; font-size:12px; color:#cfd6ff; }
</style>
</head>
<body>
<div id="app">
  <!-- Toolbar -->
  <div class="toolbar">
    <button id="refresh">Refresh</button>
    <button id="layout">Layout</button>
    <button id="fit">Fit</button>
    <button id="addNode">Create</button>
    <button id="undefer" title="Load neighbors of selected">Undefer</button>
    <button id="delete">Delete (local)</button>
    <div class="spacer"></div>

    <select id="table"></select>
    <input id="where" placeholder='where JSON e.g. {"status":"open"}' style="min-width:260px"/>
    <input id="limit" type="number" min="1" max="5000" value="50" style="width:90px"/>
    <button id="select">Select</button>
  </div>

  <!-- Graph -->
  <div id="cy"></div>

  <!-- Inspector -->
  <div class="inspector" id="inspector">
    <h3>Selection</h3>
    <div class="section" id="sel-none">
      <div class="pill">Nothing selected</div>
      <p style="color:var(--muted); margin-top:6px">Click a node to view/edit attributes.</p>
    </div>

    <div class="section" id="sel-node" style="display:none">
      <div class="kv"><label>Id</label><input id="n-id" readonly></div>
      <div class="kv"><label>Table</label><input id="n-table" readonly></div>
      <div class="kv"><label>Deferred</label><input id="n-deferred" readonly></div>
      <div class="kv"><label>PK</label><input id="n-pk" readonly></div>
      <h3 style="margin-top:12px">Attributes</h3>
      <div class="section" id="attrs"></div>
      <div class="btnrow">
        <button id="btn-undefer">Undefer</button>
        <button id="btn-save">Save</button>
      </div>
    </div>

    <div class="section" id="create-form" style="display:none">
      <h3>Create Row</h3>
      <div class="kv"><label>Table</label><input id="c-table" placeholder="user"></div>
      <div class="kv" style="grid-template-columns: 110px 1fr">
        <label>Values (JSON)</label>
        <textarea id="c-values" rows="5" placeholder='{"name":"New"}'></textarea>
      </div>
      <div class="btnrow">
        <button id="btn-create">Create</button>
      </div>
    </div>
  </div>

  <!-- Status -->
  <div class="status" id="status">Ready.</div>
</div>

<script>
cytoscape.use(cytoscapeDagre);

/* ------------------------ Cytoscape init ------------------------ */
const cy = cytoscape({
  container: document.getElementById('cy'),
  boxSelectionEnabled: true,
  wheelSensitivity: 0.2,
  style: [
    { selector: 'node',
      style: {
        'shape':'round-rectangle',
        'background-color': ele => ele.data('deferred') ? '#1a203f' : '#23306a',
        'border-width': 2,
        'border-color': ele => ele.data('deferred') ? '#c6f' : '#3b4570',
        'label':'data(label)',
        'color':'#eaf0ff',
        'font-weight':700,
        'text-wrap':'wrap',
        'text-max-width': 160,
        'text-valign':'center','text-halign':'center',
        'width': 180, 'height': 70
      }
    },
    { selector:'node:selected', style:{ 'border-color':'#6cc', 'shadow-blur':12, 'shadow-color':'#6cc', 'shadow-opacity':.4 }},
    { selector:'edge',
      style:{
        'curve-style':'bezier',
        'line-color':'#667399',
        'target-arrow-color':'#667399',
        'target-arrow-shape':'triangle',
        'width':2,
        'label':'data(rel)',
        'font-size':11,
        'text-rotation':'autorotate',
        'text-margin-y': -8,
        'color':'#9fb0d9'
      }
    },
    { selector:'edge:selected', style:{ 'line-color':'#6cc', 'target-arrow-color':'#6cc' } }
  ],
  layout:{ name:'preset' }
});

const status = (t)=> document.getElementById('status').textContent = t;

/* ------------------------ API helpers ------------------------ */
async function api(path, {method='GET', body, headers} = {}){
  const opts = { method, headers: headers || {} };
  if (body !== undefined){ opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(`/api/${path}`, opts);
  if (!r.ok) throw new Error(`${method} /api/${path} failed: ${r.status}`);
  return r.json();
}

/* ------------------------ Graph mappers ------------------------ */
/* expected node shape from API:
   { id, table, pk:{...}, attrs:{...}, deferred:boolean }
   label defaults to `${table} ${JSON.stringify(pk)}`
*/
function mapNode(n){
  return {
    group:'nodes',
    data:{
      id: n.id,
      table: n.table,
      pk: n.pk,
      attrs: n.attrs || {},
      deferred: !!n.deferred,
      label: n.attrs?.name ?? n.attrs?.title ?? `${n.table} ${JSON.stringify(n.pk)}`
    },
    position: n.position // optional (server may send)
  };
}
function mapEdge(e){
  return {
    group:'edges',
    data:{ id: e.id || `${e.source}->${e.target}`, source: e.source, target: e.target, rel: e.rel || '' }
  };
}
function upsertFromApi(payload){
  const added = { nodes:[], edges:[] };
  (payload.nodes||[]).forEach(n=>{
    const exists = cy.getElementById(n.id);
    const mapped = mapNode(n);
    if (exists.nonempty()){
      exists.data(mapped.data);
      if (mapped.position) exists.position(mapped.position);
    } else {
      const el = cy.add(mapped);
      added.nodes.push(el);
    }
  });
  (payload.edges||[]).forEach(e=>{
    const id = e.id || `${e.source}->${e.target}`;
    if (cy.getElementById(id).empty()){
      const el = cy.add(mapEdge(e));
      added.edges.push(el);
    }
  });
  return added;
}

/* ------------------------ Load initial graph ------------------------ */
async function refresh(){
  status('Loading nodes…');
  try{
    const data = await api('nodes');  // GET /api/nodes
    cy.elements().remove();
    upsertFromApi(data);
    cy.layout({ name:'dagre', nodeSep:70, rankSep:120, edgeSep:20, rankDir:'TB', animate:true, animationDuration:300 }).run();
    cy.fit(cy.elements(), 60);
    status('Loaded.');
    hydrateTableList(data.tables || data.nodes);
  }catch(e){ console.error(e); alert(e.message); status('Error.'); }
}
document.getElementById('refresh').onclick = refresh;

/* ------------------------ Undefer (expand) ------------------------ */
async function undeferSelected(){
  const node = cy.$('node:selected').first();
  if (node.empty()) return alert('Select a node.');
  status('Undefer '+node.id()+' …');
  try{
    const data = await api('undefer', { method:'POST', body:{ id: node.id() }});
    const res = upsertFromApi(data.added || data);
    node.data('deferred', false);
    if (res.nodes.length || res.edges.length) cy.layout({ name:'dagre', nodeSep:70, rankSep:120, edgeSep:20, rankDir:'TB' }).run();
    status('Undeferred.');
  }catch(e){ console.error(e); alert(e.message); status('Error.'); }
}
document.getElementById('undefer').onclick = undeferSelected;

/* ------------------------ Select-from-table ------------------------ */
function hydrateTableList(data){
  let tables;
  if (Array.isArray(data)) {
    // If data is an array of table names
    tables = data.filter(Boolean).sort();
  } else {
    // If data is an array of nodes, extract table names
    tables = Array.from(new Set((data||[]).map(n=>n.table).filter(Boolean))).sort();
  }
  const sel = document.getElementById('table');
  sel.innerHTML = '<option value="">(table)</option>' + tables.map(t=>`<option>${t}</option>`).join('');
}
async function runSelect(){
  const table = document.getElementById('table').value.trim() || document.getElementById('table').value.trim();
  const whereText = document.getElementById('where').value.trim();
  const limit = parseInt(document.getElementById('limit').value, 10) || 50;
  if (!table) return alert('Choose a table (type a name if not in the list).');
  let where = undefined;
  if (whereText){ try{ where = JSON.parse(whereText); } catch{ return alert('where must be valid JSON'); } }
  status(`Selecting from ${table} …`);
  try{
    const data = await api('select', { method:'POST', body:{ table, where, limit }});
    const res = upsertFromApi(data.added || data);
    if (res.nodes.length || res.edges.length){
      cy.layout({ name:'dagre', nodeSep:70, rankSep:120, edgeSep:20, rankDir:'TB' }).run();
      status(`Added ${res.nodes.length} nodes, ${res.edges.length} edges.`);
    } else {
      status('No results.');
    }
  }catch(e){ console.error(e); alert(e.message); status('Error.'); }
}
document.getElementById('select').onclick = runSelect;

/* ------------------------ Create ------------------------ */
function showCreateForm(){
  document.getElementById('create-form').style.display = 'block';
  document.getElementById('c-table').value = document.getElementById('table').value || '';
}
document.getElementById('addNode').onclick = showCreateForm;

document.getElementById('btn-create').onclick = async ()=>{
  const table = document.getElementById('c-table').value.trim();
  if (!table) return alert('table is required');
  let values;
  try{ values = JSON.parse(document.getElementById('c-values').value || '{}'); }
  catch{ return alert('values must be valid JSON'); }
  status('Creating…');
  try{
    const data = await api('create', { method:'POST', body:{ table, values }});
    if (data.node){
      const el = cy.add(mapNode(data.node));
      cy.center(el); el.select();
      status('Created.');
    } else {
      status('Created (no node returned).');
    }
  }catch(e){ console.error(e); alert(e.message); status('Error.'); }
};

/* ------------------------ Update (attributes) ------------------------ */
async function saveSelected(){
  const node = cy.$('node:selected').first();
  if (node.empty()) return;
  // collect from form
  const values = {};
  document.querySelectorAll('#attrs [data-key]').forEach(row=>{
    const k = row.getAttribute('data-key');
    const input = row.querySelector('input,textarea,select');
    let v = input.value;
    // naive type hint: numbers & booleans
    if (v === 'true') v = true; else if (v === 'false') v = false; else if (!isNaN(v) && v.trim() !== '') v = Number(v);
    values[k] = v;
  });
  status('Saving…');
  try{
    const data = await api('update', { method:'PUT', body:{ id: node.id(), values }});
    if (data.node){
      node.data('attrs', data.node.attrs || values);
      node.data('label', data.node.attrs?.name ?? data.node.attrs?.title ?? `${node.data('table')} ${JSON.stringify(data.node.pk || node.data('pk'))}`);
      fillInspector(node);
      status('Saved.');
    } else {
      status('Saved (no node returned).');
    }
  }catch(e){ console.error(e); alert(e.message); status('Error.'); }
}
document.getElementById('btn-save').onclick = saveSelected;

/* ------------------------ Delete (local only) ------------------------ */
document.getElementById('delete').onclick = ()=>{
  const sel = cy.$(':selected');
  if (sel.nonempty()) sel.remove();
};

/* ------------------------ Layout/Fit ------------------------ */
document.getElementById('layout').onclick = ()=> cy.layout({ name:'dagre', nodeSep:70, rankSep:120, edgeSep:20, rankDir:'TB', animate:true, animationDuration:300 }).run();
document.getElementById('fit').onclick = ()=> cy.fit(cy.elements(), 60);

/* ------------------------ Inspector ------------------------ */
const show = (id, on)=> document.getElementById(id).style.display = on ? 'block' : 'none';
function fillInspector(node){
  show('sel-none', false); show('sel-node', true);
  document.getElementById('n-id').value = node.id();
  document.getElementById('n-table').value = node.data('table') || '';
  document.getElementById('n-deferred').value = String(!!node.data('deferred'));
  document.getElementById('n-pk').value = JSON.stringify(node.data('pk') || {});
  const attrsDiv = document.getElementById('attrs');
  attrsDiv.innerHTML = '';
  const attrs = node.data('attrs') || {};
  const keys = Object.keys(attrs);
  if (keys.length === 0){
    const p = document.createElement('p'); p.style.color='var(--muted)'; p.textContent = '(no attributes)'; attrsDiv.appendChild(p);
  } else {
    keys.forEach(k=>{
      const row = document.createElement('div'); row.className='kv'; row.setAttribute('data-key', k);
      const lab = document.createElement('label'); lab.textContent = k;
      const inp = document.createElement('input'); inp.value = attrs[k] ?? '';
      row.appendChild(lab); row.appendChild(inp);
      attrsDiv.appendChild(row);
    });
  }
}
function clearInspector(){ show('sel-node', false); show('sel-none', true); }
document.getElementById('btn-undefer').onclick = undeferSelected;

cy.on('select', 'node', e=> fillInspector(e.target));
cy.on('unselect', 'node', ()=> {
  if (cy.$('node:selected').empty()) clearInspector();
});

/* ------------------------ Keyboard ------------------------ */
document.addEventListener('keydown', (e)=>{
  if ((e.key==='Delete' || e.key==='Backspace') && document.activeElement?.tagName!=='INPUT' && document.activeElement?.tagName!=='TEXTAREA'){
    cy.$(':selected').remove();
  }
  if (e.key.toLowerCase()==='l') document.getElementById('layout').click();
});

/* ------------------------ Boot ------------------------ */
refresh(); // initial load
</script>
</body>
</html>
"""

async def handle_root(request):
    return web.Response(text=index_html, content_type='text/html')

async def handle_favicon(request):
    return web.Response(status=404)

# API endpoints
async def api_nodes(request):
    """GET /api/nodes - Get all nodes for the graph"""
    logger.info("api_nodes called")
    session = get_global_session()
    try:
        nodes = []
        edges = []
        
        logger.info(f"Found {len(BaseModel.registry.mappers)} mappers in registry")
        
        # Get all model classes from the registry
        for mapper in BaseModel.registry.mappers:
            table_name = mapper.class_.__tablename__
            logger.info(f"Processing mapper for table: {table_name}")
            
            # Skip association tables
            if '_' in table_name and any(x in table_name for x in ['unit_types', 'upgrade_types', 'campaign_invites']):
                logger.info(f"Skipping association table: {table_name}")
                continue
            
            # Don't load any initial data - let user select what they want to load
            logger.info(f"Skipping initial data load for {table_name} - user will select tables to load")
        
        # Get table information from registry for dropdown
        tables = []
        for mapper in BaseModel.registry.mappers:
            table_name = mapper.class_.__tablename__
            # Skip association tables
            if '_' in table_name and any(x in table_name for x in ['unit_types', 'upgrade_types', 'campaign_invites']):
                continue
            tables.append(table_name)
        
        logger.info(f"Returning {len(nodes)} nodes and {len(tables)} tables")
        logger.info(f"Tables: {tables}")
        
        response_data = {
            "nodes": nodes, 
            "edges": edges,
            "tables": tables
        }
        
        logger.info(f"Response data: {json.dumps(response_data, indent=2)}")
        
        return web.json_response(response_data)
    except Exception as e:
        logger.error(f"Error in api_nodes: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def api_undefer(request):
    """POST /api/undefer - Load neighbors of a deferred node"""
    logger.info("api_undefer called")
    data = await request.json()
    node_id = data.get('id')
    logger.info(f"Undeferring node: {node_id}")
    
    session = get_global_session()
    try:
        # Parse node_id to get table and pk
        if ':' not in node_id:
            logger.error(f"Invalid node ID format: {node_id}")
            return web.json_response({"error": "Invalid node ID"}, status=400)
            
        table_name, pk_json = node_id.split(':', 1)
        pk = json.loads(pk_json)
        logger.info(f"Parsed table: {table_name}, pk: {pk}")
        
        # Find the model class for this table
        model_class = None
        for mapper in BaseModel.registry.mappers:
            if mapper.class_.__tablename__ == table_name:
                model_class = mapper.class_
                break
        
        if model_class is None:
            logger.error(f"Model class not found for table {table_name}")
            return web.json_response({"error": f"Model class not found for table {table_name}"}, status=404)
        
        # Query the database directly for the instance
        query = session.query(model_class)
        for key, value in pk.items():
            if hasattr(model_class, key):
                query = query.filter(getattr(model_class, key) == value)
        
        target_instance = query.first()
        
        if target_instance is None:
            logger.error(f"Instance not found in database for {node_id}")
            return web.json_response({"error": "Instance not found"}, status=404)
        
        logger.info(f"Found target instance: {target_instance}")
        
        # Get the mapper for the target instance
        mapper = inspect(target_instance).mapper
        added_nodes = []
        added_edges = []
        
        # Access all relationships to materialize them into the identity map
        for relationship in mapper.relationships:
            rel_name = relationship.key
            logger.info(f"Accessing relationship: {rel_name}")
            
            try:
                # This will trigger lazy loading and materialize related objects
                related_objects = getattr(target_instance, rel_name)
                logger.info(f"Relationship {rel_name} returned: {type(related_objects)}")
                
                # Handle different relationship types
                if hasattr(related_objects, '__iter__') and not isinstance(related_objects, str):
                    # Collection relationship (one-to-many, many-to-many)
                    for related_obj in related_objects:
                        if related_obj is not None:
                            related_mapper = inspect(related_obj).mapper
                            related_table = related_mapper.class_.__tablename__
                            
                            # Get primary key of related object
                            related_pk = {}
                            for pk_col in related_mapper.primary_key:
                                value = getattr(related_obj, pk_col.name, None)
                                related_pk[pk_col.name] = make_json_serializable(value)
                            
                            related_node_id = f"{related_table}:{json.dumps(related_pk, sort_keys=True)}"
                            
                            # Get non-primary key attributes with Enum conversion
                            attrs = {}
                            for col in related_mapper.columns:
                                if col.name not in related_pk:
                                    value = getattr(related_obj, col.name, None)
                                    attrs[col.name] = make_json_serializable(value)
                            
                            # Add node
                            added_nodes.append({
                                "id": related_node_id,
                                "table": related_table,
                                "pk": related_pk,
                                "attrs": attrs,
                                "deferred": False
                            })
                            
                            # Add edge
                            edge_id = f"{node_id}->{related_node_id}"
                            added_edges.append({
                                "id": edge_id,
                                "source": node_id,
                                "target": related_node_id,
                                "rel": rel_name
                            })
                else:
                    # Single relationship (many-to-one, one-to-one)
                    if related_objects is not None:
                        related_mapper = inspect(related_objects).mapper
                        related_table = related_mapper.class_.__tablename__
                        
                        # Get primary key of related object
                        related_pk = {}
                        for pk_col in related_mapper.primary_key:
                            value = getattr(related_objects, pk_col.name, None)
                            related_pk[pk_col.name] = make_json_serializable(value)
                        
                        related_node_id = f"{related_table}:{json.dumps(related_pk, sort_keys=True)}"
                        
                        # Get non-primary key attributes with Enum conversion
                        attrs = {}
                        for col in related_mapper.columns:
                            if col.name not in related_pk:
                                value = getattr(related_objects, col.name, None)
                                attrs[col.name] = make_json_serializable(value)
                        
                        # Add node
                        added_nodes.append({
                            "id": related_node_id,
                            "table": related_table,
                            "pk": related_pk,
                            "attrs": attrs,
                            "deferred": False
                        })
                        
                        # Add edge
                        edge_id = f"{node_id}->{related_node_id}"
                        added_edges.append({
                            "id": edge_id,
                            "source": node_id,
                            "target": related_node_id,
                            "rel": rel_name
                        })
                        
            except Exception as e:
                logger.warning(f"Error accessing relationship {rel_name}: {e}")
                continue
        
        logger.info(f"Found {len(added_nodes)} related nodes and {len(added_edges)} edges")
        
        return web.json_response({
            "added": {
                "nodes": added_nodes,
                "edges": added_edges
            }
        })
    except Exception as e:
        logger.error(f"Error in api_undefer: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def api_select(request):
    """POST /api/select - Select nodes from a table with where/limit"""
    logger.info("api_select called")
    data = await request.json()
    table_name = data.get('table')
    where_clause = data.get('where', {})
    limit = data.get('limit', 50)
    logger.info(f"Selecting from table: {table_name}, where: {where_clause}, limit: {limit}")
    
    session = get_global_session()
    try:
        # Build WHERE clause
        where_parts = []
        params = {}
        for key, value in where_clause.items():
            where_parts.append(f"{key} = :{key}")
            params[key] = value
            
        where_sql = " AND ".join(where_parts) if where_parts else "1=1"
        logger.info(f"WHERE SQL: {where_sql}")
        logger.info(f"Params: {params}")
        
        # Get table info
        table = BaseModel.metadata.tables.get(table_name)
        if table is None:
            logger.error(f"Table {table_name} not found in metadata")
            return web.json_response({"error": f"Table {table_name} not found"}, status=404)
            
        pk_columns = [col.name for col in table.primary_key.columns]
        logger.info(f"Primary key columns: {pk_columns}")
        
        # Find the model class for this table
        model_class = None
        for mapper in BaseModel.registry.mappers:
            if mapper.class_.__tablename__ == table_name:
                model_class = mapper.class_
                break
        
        if model_class is None:
            logger.error(f"Model class not found for table {table_name}")
            return web.json_response({"error": f"Model class not found for table {table_name}"}, status=404)
        
        # Use ORM query to populate identity map
        query = session.query(model_class)
        
        # Apply WHERE conditions
        for key, value in where_clause.items():
            if hasattr(model_class, key):
                query = query.filter(getattr(model_class, key) == value)
        
        # Apply limit
        query = query.limit(limit)
        
        logger.info(f"Executing ORM query for {model_class.__name__}")
        instances = query.all()
        logger.info(f"Found {len(instances)} instances")
        logger.info(f"Identity map now has {len(session.identity_map)} instances")
        
        nodes = []
        for instance in instances:
            # Get primary key values
            pk = {}
            for pk_col in mapper.primary_key:
                value = getattr(instance, pk_col.name, None)
                pk[pk_col.name] = make_json_serializable(value)
            
            node_id = f"{table_name}:{json.dumps(pk, sort_keys=True)}"
            
            # Get non-primary key attributes
            attrs = {}
            for column in mapper.columns:
                if column.name not in pk:
                    value = getattr(instance, column.name, None)
                    attrs[column.name] = make_json_serializable(value)
            
            nodes.append({
                "id": node_id,
                "table": table_name,
                "pk": pk,
                "attrs": attrs,
                "deferred": False
            })
        
        logger.info(f"Found {len(nodes)} nodes")
        return web.json_response({
            "added": {
                "nodes": nodes,
                "edges": []
            }
        })
    except Exception as e:
        logger.error(f"Error in api_select: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def api_create(request):
    """POST /api/create - Create a new row"""
    data = await request.json()
    table_name = data.get('table')
    values = data.get('values', {})
    
    session = get_global_session()
    try:
        table = BaseModel.metadata.tables.get(table_name)
        if table is None:
            return web.json_response({"error": f"Table {table_name} not found"}, status=404)
        
        # Find the model class for this table
        model_class = None
        for mapper in BaseModel.registry.mappers:
            if mapper.class_.__tablename__ == table_name:
                model_class = mapper.class_
                break
        
        if model_class is None:
            return web.json_response({"error": f"Model class not found for table {table_name}"}, status=404)
        
        # Create new instance using ORM
        instance = model_class(**values)
        session.add(instance)
        session.commit()
        session.refresh(instance)  # Get the instance with all fields populated
        
        # Get primary key values
        pk = {}
        for pk_col in mapper.primary_key:
            value = getattr(instance, pk_col.name, None)
            pk[pk_col.name] = make_json_serializable(value)
        
        node_id = f"{table_name}:{json.dumps(pk, sort_keys=True)}"
        
        # Get non-primary key attributes
        attrs = {}
        for column in mapper.columns:
            if column.name not in pk:
                value = getattr(instance, column.name, None)
                # Convert Enum values to strings for JSON serialization
                if hasattr(value, 'value'):  # It's an Enum
                    value = value.value
                attrs[column.name] = value
        
        return web.json_response({
            "node": {
                "id": node_id,
                "table": table_name,
                "pk": pk,
                "attrs": attrs,
                "deferred": False
            }
        })
    except Exception as e:
        session.rollback()
        return web.json_response({"error": str(e)}, status=500)

async def api_update(request):
    """PUT /api/update - Update node attributes"""
    data = await request.json()
    node_id = data.get('id')
    values = data.get('values', {})
    
    session = get_global_session()
    try:
        # Parse node_id
        if ':' not in node_id:
            return web.json_response({"error": "Invalid node ID"}, status=400)
            
        table_name, pk_json = node_id.split(':', 1)
        pk = json.loads(pk_json)
        
        table = BaseModel.metadata.tables.get(table_name)
        if table is None:
            return web.json_response({"error": f"Table {table_name} not found"}, status=404)
        
        # Build UPDATE statement
        set_parts = [f"{col} = :{col}" for col in values.keys()]
        where_parts = [f"{col} = :pk_{col}" for col in pk.keys()]
        
        sql = f"UPDATE {table_name} SET {', '.join(set_parts)} WHERE {' AND '.join(where_parts)}"
        
        # Prepare parameters
        params = values.copy()
        for key, value in pk.items():
            params[f"pk_{key}"] = value
            
        session.execute(text(sql), params)
        session.commit()
        
        # Return updated node
        where_sql = " AND ".join([f"{col} = :{col}" for col in pk.keys()])
        select_sql = f"SELECT * FROM {table_name} WHERE {where_sql}"
        result = session.execute(text(select_sql), pk)
        row = result.fetchone()
        
        if row:
            row_dict = dict(row._mapping)
            pk_columns = [col.name for col in table.primary_key.columns]
            pk_dict = {col: row_dict.get(col) for col in pk_columns}
            
            return web.json_response({
                "node": {
                    "id": node_id,
                    "table": table_name,
                    "pk": pk_dict,
                    "attrs": {k: v for k, v in row_dict.items() if k not in pk_columns},
                    "deferred": False
                }
            })
        
        return web.json_response({"node": None})
    except Exception as e:
        session.rollback()
        return web.json_response({"error": str(e)}, status=500)

def create_app():
    app = web.Application(middlewares=[auth_middleware])
    
    # Static routes
    app.router.add_get('/', handle_root)
    app.router.add_get('/favicon.ico', handle_favicon)
    
    # API routes
    app.router.add_get('/api/nodes', api_nodes)
    app.router.add_post('/api/undefer', api_undefer)
    app.router.add_post('/api/select', api_select)
    app.router.add_post('/api/create', api_create)
    app.router.add_put('/api/update', api_update)
    
    return app

def parse_args():
    """Parse command line arguments for -b host:port or -b port and -a user:pass"""
    host = '127.0.0.1'
    port = 8080
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        
        if arg == '-b' and i + 1 < len(sys.argv):
            bind_arg = sys.argv[i + 1]
            if ':' in bind_arg:
                host, port = bind_arg.split(':', 1)
                port = int(port) if port else 0
            else:
                host = "127.0.0.1"
                port = int(bind_arg) if bind_arg else 8080
            i += 2
        elif arg.startswith('-b '):
            bind_spec = arg[3:]  # Remove '-b '
            if ':' in bind_spec:
                host, port = bind_spec.split(':', 1)
                port = int(port) if port else 0
            else:
                host = "127.0.0.1"
                port = int(bind_spec) if bind_spec else 8080
            i += 1
        elif arg == '-a' and i + 1 < len(sys.argv):
            auth_spec = sys.argv[i + 1]
            if ':' in auth_spec:
                username, password = auth_spec.split(':', 1)
                auth_credentials.append((username, password))
                logger.info(f"Added auth credential: {username}")
            else:
                logger.warning(f"Invalid auth format: {auth_spec}")
            i += 2
        else:
            i += 1
    
    return host, port

# Global socket for cleanup
_socket = None

def cleanup_socket():
    """Clean up the socket on exit"""
    global _socket
    if _socket:
        import socket
        try:
            _socket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            _socket.close()
            print("Socket closed.")
        except:
            pass
        _socket = None

def signal_handler(signum, frame):
    """Handle interrupt signals"""
    print(f"\nReceived signal {signum}, shutting down...")
    cleanup_socket()
    sys.exit(0)

if __name__ == '__main__':
    host, port = parse_args()
    app = create_app()
    
    import socket
    _socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _socket.bind((host, port))
    
    # Register cleanup handlers
    atexit.register(cleanup_socket)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    actual_host, actual_port = _socket.getsockname()
    print(f"Server will start on {actual_host}:{actual_port}")
    
    try:
        web.run_app(app, sock=_socket)
    finally:
        cleanup_socket()