/* ════════════════════════════════════════════════════════════
   KSK SYNC — Общий слой данных для трёх порталов
   Министерство ↔ Региональный отдел ↔ Инспектор
   ────────────────────────────────────────────────────────────
   Vanilla JS · localStorage · BroadcastChannel
   Используется на всех трёх HTML-страницах одновременно.
   ════════════════════════════════════════════════════════════ */

(function(global){
'use strict';

var STORAGE_KEY = 'ksk_data_v1';
var CHANNEL_NAME = 'ksk_channel';
var SCHEMA_VERSION = 1;

// ──────── СЕМЕНА (первичные данные) ────────
// Инспекторы — те же, что в кабинете инспектора (id 1–12)

var SEED_INSPECTORS = [
  {id:1,name:'Шергазиев Э.Ш.',ph:'ШЭ',reg:'Бишкек',dept:'Управление ГАСК по ЦА',pos:'Старший инспектор',rating:88,phone:'+996 700 111 001',email:'sherg@dgask.gov.kg'},
  {id:2,name:'Джузумалиев А.',ph:'ДА',reg:'Бишкек',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:81,phone:'+996 700 111 002',email:'dzhuz@dgask.gov.kg'},
  {id:3,name:'Максатбеков М.',ph:'ММ',reg:'Бишкек',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:92,phone:'+996 700 111 003',email:'maks@dgask.gov.kg'},
  {id:4,name:'Заиров Т.',ph:'ЗТ',reg:'Чуйская обл.',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:74,phone:'+996 700 111 004',email:'zair@dgask.gov.kg'},
  {id:5,name:'Кайназарова Ч.',ph:'КЧ',reg:'Иссык-Кульская',dept:'Управление ГАСК по ЦА',pos:'Старший инспектор',rating:95,phone:'+996 700 111 005',email:'kayn@dgask.gov.kg'},
  {id:6,name:'Юсупов А.А.',ph:'ЮА',reg:'Ошская обл.',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:67,phone:'+996 700 111 006',email:'yusup@dgask.gov.kg'},
  {id:7,name:'Бузурманкул уулу Айбек',ph:'БА',reg:'Нарынская обл.',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:79,phone:'+996 700 111 007',email:'buz@dgask.gov.kg'},
  {id:8,name:'Замир уулу Эрлан',ph:'ЗЭ',reg:'Баткенская обл.',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:83,phone:'+996 700 111 008',email:'zam@dgask.gov.kg'},
  {id:9,name:'Дуйшонкул уулу Каныбек',ph:'ДК',reg:'Таласская обл.',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:77,phone:'+996 700 111 009',email:'duy@dgask.gov.kg'},
  {id:10,name:'Кутпидинов Арген',ph:'КА',reg:'Джалал-Абадская',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:85,phone:'+996 700 111 010',email:'kut@dgask.gov.kg'},
  {id:11,name:'Мамонова Айгул',ph:'МА',reg:'Бишкек',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:89,phone:'+996 700 111 011',email:'mam@dgask.gov.kg'},
  {id:12,name:'Жаамакеев Н.',ph:'ЖН',reg:'Бишкек',dept:'Управление ГАСК по ЦА',pos:'Инспектор',rating:72,phone:'+996 700 111 012',email:'zhaam@dgask.gov.kg'}
];

// Региональные начальники (по областям)
var SEED_REGIONALS = [
  {region:'Бишкек',name:'Айдар уулу Эрнис',init:'ЭА',pos:'Начальник регионального отдела ДГАСК по г. Бишкек'},
  {region:'Чуйская обл.',name:'Айдар уулу Эрнис',init:'ЭА',pos:'Начальник регионального отдела ДГАСК по Чуйской обл.'},
  {region:'Иссык-Кульская',name:'Бакыт Турдубеков',init:'БТ',pos:'Начальник регионального отдела ДГАСК по Иссык-Кульской обл.'},
  {region:'Ошская обл.',name:'Нурбек Маматов',init:'НМ',pos:'Начальник регионального отдела ДГАСК по Ошской обл.'},
  {region:'Нарынская обл.',name:'Канат Орозбеков',init:'КО',pos:'Начальник регионального отдела ДГАСК по Нарынской обл.'},
  {region:'Баткенская обл.',name:'Эрмек Сатыбалдиев',init:'ЭС',pos:'Начальник регионального отдела ДГАСК по Баткенской обл.'},
  {region:'Таласская обл.',name:'Аман Молдошев',init:'АМ',pos:'Начальник регионального отдела ДГАСК по Таласской обл.'},
  {region:'Джалал-Абадская',name:'Уланбек Жумабаев',init:'УЖ',pos:'Начальник регионального отдела ДГАСК по Джалал-Абадской обл.'}
];

// Демо-отчёты (для затравки UI)
var SEED_REPORTS = [
  {
    id:'r-seed-001',insId:1,month:'апрель 2026',submitted:'2026-05-04 09:14',status:'pending',daysPending:3,
    data:{uved:18,plan:6,vneplan:4,kontrol:2,nar:9,aktov:8,aktS:5,aktN:3,pred:7,prot:4,post:2,nalog:340,vzisk:280,zhal:3,pis:5,podtv:12,priemka:4,sudy:1,prav:0,prok:0,izhsP:14,izhsPt:11,izhsO:3,obj:8},
    notes:'Один объект приостановлен по предписанию.',
    history:[{who:'ШЭ',role:'ins',name:'Шергазиев Э.Ш.',time:'04.05.2026 09:14',text:'Отчёт отправлен на согласование в региональный отдел.'}]
  },
  {
    id:'r-seed-002',insId:3,month:'апрель 2026',submitted:'2026-05-03 17:42',status:'pending',daysPending:4,
    data:{uved:22,plan:8,vneplan:3,kontrol:1,nar:6,aktov:10,aktS:8,aktN:2,pred:5,prot:3,post:1,nalog:215,vzisk:215,zhal:1,pis:4,podtv:18,priemka:7,sudy:0,prav:0,prok:0,izhsP:19,izhsPt:17,izhsO:2,obj:7},
    notes:'Все плановые проверки выполнены в срок.',
    history:[{who:'ММ',role:'ins',name:'Максатбеков М.',time:'03.05.2026 17:42',text:'Отчёт отправлен на согласование в региональный отдел.'}]
  },
  {
    id:'r-seed-003',insId:4,month:'апрель 2026',submitted:'2026-05-02 11:08',status:'clarify',daysPending:5,
    data:{uved:14,plan:5,vneplan:5,kontrol:2,nar:8,aktov:7,aktS:4,aktN:3,pred:6,prot:5,post:3,nalog:425,vzisk:310,zhal:2,pis:3,podtv:9,priemka:3,sudy:2,prav:1,prok:0,izhsP:11,izhsPt:9,izhsO:2,obj:6},
    notes:'Передано 3 дела в правоохранительные органы.',
    history:[
      {who:'ЗТ',role:'ins',name:'Заиров Т.',time:'02.05.2026 11:08',text:'Отчёт отправлен на согласование.'},
      {who:'ЭА',role:'reg',name:'Айдар уулу Эрнис',time:'03.05.2026 10:15',text:'Уточните, как соотносится число протоколов (5) с актами несоответствия (3).'}
    ]
  },
  {
    id:'r-seed-004',insId:11,month:'март 2026',reportType:'monthly',period:'март 2026',submitted:'2026-04-12 14:30',status:'approved',approvedDate:'2026-04-14 11:22',
    data:{uved:20,plan:7,vneplan:4,kontrol:2,nar:7,aktov:9,aktS:7,aktN:2,pred:6,prot:4,post:2,nalog:265,vzisk:245,zhal:1,pis:4,podtv:14,priemka:6,sudy:0,prav:0,prok:0,izhsP:16,izhsPt:14,izhsO:2,obj:7},
    notes:'Без замечаний.',
    history:[
      {who:'МА',role:'ins',name:'Мамонова Айгул',time:'12.04.2026 14:30',text:'Отчёт отправлен на согласование.'},
      {who:'ЭА',role:'reg',name:'Айдар уулу Эрнис',time:'14.04.2026 11:22',text:'Согласовано. Показатели подтверждены. Отправлено в ДГАСК.'}
    ]
  },
  // Демо-еженедельный отчёт
  {
    id:'r-seed-005',insId:1,reportType:'weekly',period:'нед. 19 (04.05–10.05.2026)',month:'нед. 19 (04.05–10.05.2026)',submitted:'2026-05-12 10:30',status:'pending',daysPending:2,
    data:{uved:4,plan:2,vneplan:1,kontrol:0,nar:3,aktov:2,aktS:1,aktN:1,pred:2,prot:1,post:0,nalog:85,vzisk:60,obj:8,plans:'Завершить плановую проверку ЖК «Алатоо Сити». Выезд на контрольный объект ИЖС в Кант.'},
    notes:'',
    history:[{who:'ШЭ',role:'ins',name:'Шергазиев Э.Ш.',time:'12.05.2026 10:30',text:'Еженедельный отчёт отправлен на согласование в региональный отдел.'}]
  },
  // Демо-отчёт о проделанной работе
  {
    id:'r-seed-006',insId:3,reportType:'work',period:'апрель 2026',month:'апрель 2026',submitted:'2026-05-05 11:00',status:'approved',approvedDate:'2026-05-07 14:00',
    data:{visits:24,overtime:18,trips:3,activity:'Проведены плановые проверки 7 объектов жилого и социального строительства. Выявлены нарушения, выданы предписания. Завершён контроль реконструкции школы №18.',achievements:'Полностью устранены нарушения на 5 объектах. Взыскано штрафов на 215 тыс. сом.',problems:'Сложности с доступом к проектной документации у двух подрядчиков.',proposals:'Внести в регламент обязательную выдачу проектной документации инспектору в первый день проверки.'},
    notes:'',
    history:[
      {who:'ММ',role:'ins',name:'Максатбеков М.',time:'05.05.2026 11:00',text:'Отчёт о проделанной работе отправлен на согласование.'},
      {who:'ЭА',role:'reg',name:'Айдар уулу Эрнис',time:'07.05.2026 14:00',text:'Согласовано. Принимаем предложение о регламенте к рассмотрению.'}
    ]
  }
];

var SEED_AUDIT = [
  {time:'04.05.2026 09:14',type:'submit',color:'orange',text:'Шергазиев Э.Ш. отправил отчёт за апрель 2026 на рассмотрение'},
  {time:'03.05.2026 17:42',type:'submit',color:'orange',text:'Максатбеков М. отправил отчёт за апрель 2026 на рассмотрение'},
  {time:'03.05.2026 10:15',type:'clarify',color:'blue',text:'Запрошено уточнение по отчёту Заирова Т.'},
  {time:'14.04.2026 11:22',type:'approve',color:'green',text:'Согласован отчёт Мамоновой А. за март 2026 — отправлен в ДГАСК'}
];

// ──────── СОСТОЯНИЕ ────────

var state = null;
var listeners = [];
var bc = null;

// ──────── ИНИЦИАЛИЗАЦИЯ ────────

function init(){
  state = load();
  if(!state){
    state = createSeedState();
    save(true);
  }
  // BroadcastChannel — мгновенная синхронизация между вкладками
  if(typeof BroadcastChannel !== 'undefined'){
    try {
      bc = new BroadcastChannel(CHANNEL_NAME);
      bc.onmessage = onChannel;
    } catch(e){
      console.warn('KSK: BroadcastChannel unavailable', e);
    }
  }
  // storage event — fallback (срабатывает в других вкладках)
  if(typeof window !== 'undefined'){
    window.addEventListener('storage', onStorage);
  }
}

function load(){
  try {
    var raw = localStorage.getItem(STORAGE_KEY);
    if(!raw) return null;
    var p = JSON.parse(raw);
    if(p.schema !== SCHEMA_VERSION) return null;
    return p;
  } catch(e){
    return null;
  }
}

function save(silent){
  state.lastUpdate = Date.now();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch(e){
    console.warn('KSK: save failed', e);
  }
  if(!silent){
    broadcast({type:'state:updated', actor: state.lastActor||'system', ts: state.lastUpdate});
  }
}

function broadcast(msg){
  if(bc){
    try { bc.postMessage(msg); } catch(e){}
  }
}

function onChannel(ev){
  var msg = ev.data || {};
  state = load();
  notify(msg);
}

function onStorage(ev){
  if(ev.key !== STORAGE_KEY) return;
  state = load();
  notify({type:'state:updated', source:'storage'});
}

function notify(msg){
  for(var i=0;i<listeners.length;i++){
    try { listeners[i](msg, state); } catch(e){ console.warn(e); }
  }
}

function createSeedState(){
  return {
    schema: SCHEMA_VERSION,
    inspectors: SEED_INSPECTORS,
    regionals: SEED_REGIONALS,
    reports: SEED_REPORTS,
    audit: SEED_AUDIT,
    notifications: { inspector:{}, regional:{}, ministry:[] },
    lastUpdate: Date.now(),
    lastActor: 'seed'
  };
}

// ──────── УТИЛИТЫ ────────

function nowIso(){
  var d = new Date();
  function pad(n){return n<10?'0'+n:''+n}
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+' '+pad(d.getHours())+':'+pad(d.getMinutes());
}

function nowDate(){
  var d = new Date();
  function pad(n){return n<10?'0'+n:''+n}
  return pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear()+' '+pad(d.getHours())+':'+pad(d.getMinutes());
}

function shortName(fn){
  var p = fn.split(' ');
  if(p.length>=3) return p[0]+' '+p[1].charAt(0)+'.'+p[2].charAt(0)+'.';
  if(p.length===2) return p[0]+' '+p[1].charAt(0)+'.';
  return fn;
}

function genId(){
  return 'r-'+Date.now()+'-'+Math.random().toString(36).slice(2,7);
}

function pushInspNotif(insId, n){
  var k = String(insId);
  if(!state.notifications.inspector[k]) state.notifications.inspector[k] = [];
  state.notifications.inspector[k].unshift(n);
}

function pushRegNotif(region, n){
  if(!state.notifications.regional[region]) state.notifications.regional[region] = [];
  state.notifications.regional[region].unshift(n);
}

function pushMinNotif(n){
  state.notifications.ministry.unshift(n);
}

// ──────── ПУБЛИЧНОЕ API ────────

var KSK = {

  // Подписка на изменения. Возвращает unsubscribe-функцию.
  onUpdate: function(cb){
    listeners.push(cb);
    return function(){
      for(var i=0;i<listeners.length;i++){
        if(listeners[i]===cb){ listeners.splice(i,1); break; }
      }
    };
  },

  // ──── ЧТЕНИЕ ────

  getReports: function(){ return (state.reports||[]).slice(); },

  getReport: function(id){
    for(var i=0;i<state.reports.length;i++){
      if(state.reports[i].id===id) return state.reports[i];
    }
    return null;
  },

  getReportsByInspector: function(insId){
    var key = parseInt(insId,10);
    var out = [];
    for(var i=0;i<state.reports.length;i++){
      if(parseInt(state.reports[i].insId,10)===key) out.push(state.reports[i]);
    }
    return out;
  },

  getReportsByRegion: function(region){
    var out = [];
    for(var i=0;i<state.reports.length;i++){
      var r = state.reports[i];
      var ins = this.getInspector(r.insId);
      if(ins && ins.reg===region) out.push(r);
    }
    return out;
  },

  getReportsByType: function(type){
    // type: 'monthly' | 'weekly' | 'work' | undefined (вернёт все)
    if(!type) return this.getReports();
    var out = [];
    for(var i=0;i<state.reports.length;i++){
      var rt = state.reports[i].reportType || 'monthly';
      if(rt===type) out.push(state.reports[i]);
    }
    return out;
  },

  getInspectors: function(){ return (state.inspectors||[]).slice(); },

  getInspector: function(id){
    var key = parseInt(id,10);
    for(var i=0;i<state.inspectors.length;i++){
      if(parseInt(state.inspectors[i].id,10)===key) return state.inspectors[i];
    }
    return null;
  },

  getRegional: function(region){
    for(var i=0;i<state.regionals.length;i++){
      if(state.regionals[i].region===region) return state.regionals[i];
    }
    return null;
  },

  getAudit: function(){ return (state.audit||[]).slice(); },

  getNotifications: function(role, key){
    if(role==='inspector'){ return (state.notifications.inspector[String(key)]||[]).slice(); }
    if(role==='regional'){ return (state.notifications.regional[key]||[]).slice(); }
    if(role==='ministry'){ return (state.notifications.ministry||[]).slice(); }
    return [];
  },

  // ──── ДЕЙСТВИЯ ИНСПЕКТОРА ────

  submitReport: function(payload){
    // payload: {insId, reportType?, month?, period?, data, notes}
    // reportType: 'monthly' (default) | 'weekly' | 'work'
    var ins = this.getInspector(payload.insId);
    if(!ins) return null;

    var rType = payload.reportType || 'monthly';
    var rPeriod = payload.period || payload.month || '';

    // Локализованные ярлыки для типов
    var typeLbl = {monthly:'Месячный отчёт ГАСК', weekly:'Еженедельный отчёт', work:'Отчёт о проделанной работе'}[rType] || 'Отчёт';
    var typeShort = {monthly:'месячный', weekly:'еженедельный', work:'о проделанной работе'}[rType] || 'отчёт';

    var r = {
      id: payload.id || genId(),
      insId: parseInt(payload.insId,10),
      reportType: rType,
      period: rPeriod,
      month: rPeriod, // обратная совместимость
      submitted: nowIso(),
      status: 'pending',
      daysPending: 0,
      data: payload.data || {},
      notes: payload.notes || '',
      history: [{ who: ins.ph, role:'ins', name: ins.name, time: nowDate(), text: typeLbl+' отправлен на согласование в региональный отдел.' }]
    };

    state.reports.unshift(r);

    state.audit.unshift({
      time: nowDate(), type:'submit', color:'orange',
      text: ins.name+' отправил '+typeShort+' отчёт за '+rPeriod+' на рассмотрение'
    });

    // Уведомление региональному
    pushRegNotif(ins.reg, {
      time: nowDate(), from: ins.name, type:'submit', ico:'📋',
      title:'Новый отчёт на согласование',
      text: typeLbl+' за '+rPeriod+' от '+(ins.pos||'инспектора')+' '+shortName(ins.name)+'.',
      reportId: r.id, reportType: rType, read:false
    });

    state.lastActor = 'inspector:'+ins.id;
    save();
    broadcast({type:'report:submitted', reportId: r.id, insId: ins.id, region: ins.reg, reportType: rType, actor:'inspector'});
    return r;
  },

  // Повторная отправка после возврата
  resubmitReport: function(id, newData, comment){
    var r = this.getReport(id); if(!r) return null;
    var ins = this.getInspector(r.insId);
    if(!ins) return null;
    r.status = 'pending';
    if(newData) r.data = newData;
    r.submitted = nowIso();
    r.daysPending = 0;
    r.history.push({ who: ins.ph, role:'ins', name: ins.name, time: nowDate(), text: (comment||'Отчёт скорректирован и повторно отправлен на согласование.') });

    state.audit.unshift({
      time: nowDate(), type:'submit', color:'orange',
      text: ins.name+' повторно отправил отчёт за '+r.month
    });
    pushRegNotif(ins.reg, {
      time: nowDate(), from: ins.name, type:'resubmit', ico:'🔄',
      title:'Отчёт повторно отправлен',
      text:'Инспектор '+shortName(ins.name)+' исправил отчёт за '+r.month+' и направил повторно. '+(comment||''),
      reportId: r.id, read:false
    });
    state.lastActor = 'inspector:'+ins.id;
    save();
    broadcast({type:'report:resubmitted', reportId: id, insId: ins.id, region: ins.reg, actor:'inspector'});
    return r;
  },

  // ──── ДЕЙСТВИЯ РЕГИОНАЛЬНОГО ОТДЕЛА ────

  approveReport: function(id, comment, region){
    var r = this.getReport(id); if(!r) return null;
    var ins = this.getInspector(r.insId); if(!ins) return null;
    var reg = region || ins.reg;
    var head = this.getRegional(reg) || {name:'Региональный отдел', init:'РО'};

    r.status = 'approved';
    r.approvedDate = nowDate();
    r.history.push({
      who: head.init, role:'reg', name: head.name, time: nowDate(),
      text:'Согласовано. '+(comment||'Показатели подтверждены без замечаний.')+' Отправлено в ДГАСК.'
    });

    state.audit.unshift({
      time: nowDate(), type:'approve', color:'green',
      text:'Согласован отчёт '+shortName(ins.name)+' за '+r.month+' — отправлен в ДГАСК'
    });

    pushInspNotif(ins.id, {
      time: nowDate(), from: head.name, type:'approved', ico:'✅',
      title:'Отчёт согласован',
      text:'Ваш отчёт за '+r.month+' согласован региональным отделом и отправлен в ДГАСК.',
      reportId: r.id, read:false
    });

    pushMinNotif({
      time: nowDate(), from: head.name, type:'new_report', ico:'📋',
      title:'Новый отчёт в ДГАСК',
      text:'Отчёт инспектора '+shortName(ins.name)+' ('+ins.reg+') за '+r.month+' принят в ДГАСК.',
      reportId: r.id, insId: ins.id, read:false
    });

    state.lastActor = 'regional:'+reg;
    save();
    broadcast({type:'report:approved', reportId: id, insId: ins.id, region: reg, actor:'regional'});
    return r;
  },

  rejectReport: function(id, reason, comment, region){
    var r = this.getReport(id); if(!r) return null;
    var ins = this.getInspector(r.insId); if(!ins) return null;
    var reg = region || ins.reg;
    var head = this.getRegional(reg) || {name:'Региональный отдел', init:'РО'};

    var labels = {
      cnt:'Несоответствие данным журнала',
      arith:'Арифметические ошибки',
      docs:'Отсутствуют документы',
      format:'Нарушен формат',
      other:'Иное'
    };
    var rLbl = labels[reason] || 'Иное';

    r.status = 'rejected';
    r.history.push({
      who: head.init, role:'reg', name: head.name, time: nowDate(),
      text:'Возврат ('+rLbl+'): '+(comment||'')
    });

    state.audit.unshift({
      time: nowDate(), type:'reject', color:'red',
      text:'Возвращён отчёт '+shortName(ins.name)+' — '+rLbl
    });

    pushInspNotif(ins.id, {
      time: nowDate(), from: head.name, type:'rejected', ico:'↩',
      title:'Отчёт возвращён на доработку',
      text:'Региональный отдел вернул ваш отчёт за '+r.month+'. Причина: '+rLbl+'. '+(comment||''),
      reportId: r.id, read:false
    });

    state.lastActor = 'regional:'+reg;
    save();
    broadcast({type:'report:rejected', reportId: id, insId: ins.id, region: reg, actor:'regional'});
    return r;
  },

  clarifyReport: function(id, question, region){
    var r = this.getReport(id); if(!r) return null;
    var ins = this.getInspector(r.insId); if(!ins) return null;
    var reg = region || ins.reg;
    var head = this.getRegional(reg) || {name:'Региональный отдел', init:'РО'};

    r.status = 'clarify';
    r.history.push({
      who: head.init, role:'reg', name: head.name, time: nowDate(),
      text: question
    });

    state.audit.unshift({
      time: nowDate(), type:'clarify', color:'blue',
      text:'Запрошено уточнение по отчёту '+shortName(ins.name)
    });

    pushInspNotif(ins.id, {
      time: nowDate(), from: head.name, type:'clarify', ico:'💬',
      title:'Запрос уточнения',
      text: question,
      reportId: r.id, read:false
    });

    state.lastActor = 'regional:'+reg;
    save();
    broadcast({type:'report:clarify', reportId: id, insId: ins.id, region: reg, actor:'regional'});
    return r;
  },

  // ──── СВОДНАЯ СТАТИСТИКА ДЛЯ МИНИСТЕРСТВА ────

  getMinistryStats: function(){
    var s = {
      totalReports:0, approved:0, pending:0, clarify:0, rejected:0,
      uved:0, plan:0, vneplan:0, kontrol:0, totalChecks:0,
      nar:0, aktov:0, aktS:0, aktN:0, pred:0, prot:0, post:0,
      nalog:0, vzisk:0, sudy:0, prav:0, prok:0,
      izhsP:0, izhsPt:0, izhsO:0, obj:0,
      byRegion:{},
      byType:{monthly:{total:0,approved:0,pending:0},weekly:{total:0,approved:0,pending:0},work:{total:0,approved:0,pending:0}}
    };
    for(var i=0;i<state.reports.length;i++){
      var r = state.reports[i];
      var rt = r.reportType || 'monthly';
      s.totalReports++;
      // Разбивка по типам
      if(s.byType[rt]){
        s.byType[rt].total++;
        if(r.status==='approved') s.byType[rt].approved++;
        if(r.status==='pending'||r.status==='clarify') s.byType[rt].pending++;
      }
      if(r.status==='pending') s.pending++;
      if(r.status==='clarify') s.clarify++;
      if(r.status==='rejected') s.rejected++;
      if(r.status!=='approved') continue;
      s.approved++;
      // Суммируем только статистику из ежемесячных и еженедельных
      // («работа» — описательный, без числовых KPI)
      if(rt==='work') continue;
      var d = r.data || {};
      s.uved += d.uved||0; s.plan += d.plan||0; s.vneplan += d.vneplan||0; s.kontrol += d.kontrol||0;
      s.nar += d.nar||0; s.aktov += d.aktov||0; s.aktS += d.aktS||0; s.aktN += d.aktN||0;
      s.pred += d.pred||0; s.prot += d.prot||0; s.post += d.post||0;
      s.nalog += d.nalog||0; s.vzisk += d.vzisk||0;
      s.sudy += d.sudy||0; s.prav += d.prav||0; s.prok += d.prok||0;
      s.izhsP += d.izhsP||0; s.izhsPt += d.izhsPt||0; s.izhsO += d.izhsO||0;
      s.obj += d.obj||0;

      // По региону
      var ins = this.getInspector(r.insId);
      if(ins){
        var reg = ins.reg;
        if(!s.byRegion[reg]) s.byRegion[reg] = {reports:0,obj:0,nar:0,nalog:0,vzisk:0};
        s.byRegion[reg].reports++;
        s.byRegion[reg].obj += d.obj||0;
        s.byRegion[reg].nar += d.nar||0;
        s.byRegion[reg].nalog += d.nalog||0;
        s.byRegion[reg].vzisk += d.vzisk||0;
      }
    }
    s.totalChecks = s.plan + s.vneplan + s.kontrol;
    return s;
  },

  // ──── ОТМЕТКА ПРОЧИТАНО ────

  markNotifRead: function(role, key, idx){
    var list = role==='inspector' ? state.notifications.inspector[String(key)] :
               role==='regional' ? state.notifications.regional[key] :
               state.notifications.ministry;
    if(list && list[idx]){ list[idx].read = true; save(); }
  },

  markAllNotifsRead: function(role, key){
    var list = role==='inspector' ? state.notifications.inspector[String(key)] :
               role==='regional' ? state.notifications.regional[key] :
               state.notifications.ministry;
    if(!list) return;
    for(var i=0;i<list.length;i++) list[i].read = true;
    save();
  },

  // ──── СБРОС (для дебага) ────

  reset: function(){
    state = createSeedState();
    save();
    broadcast({type:'state:reset', actor:'system'});
  },

  // ──── НИЗКОУРОВНЕВОЕ ────

  _state: function(){ return state; },
  _save: function(){ save(); },
  _broadcast: function(m){ broadcast(m); }
};

init();
global.KSK = KSK;

if(typeof console!=='undefined') console.log('[KSK SYNC] инициализирован. Отчётов:', state.reports.length, '· Инспекторов:', state.inspectors.length);

})(typeof window!=='undefined'?window:this);
