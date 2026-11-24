// The GLM-5.4 review caught a lost parcel on a failed delivery. Only a correct delivery
// consumes the parcel. Keyboard, touch and the automated player all use the same rule.
function destination(item) { return (item[0] + item[1] + 3) % 3; }

function start(L) {
  return {score:0, hits:0, mistakes:0, elapsed:0, done:false, won:false,
    lastLane:-1, lastAt:-2, correct:false};
}

function postbox(lane) { return {x: .028 + lane / 3, y: .63, w: 1 / 3 - .056, h:.26}; }

function step(s, e, L) {
  if (s.done) return s;
  if (e.type === 'tick') {
    s.elapsed += e.dt;
    if (s.elapsed >= L.seconds) s.done = true;
    return s;
  }
  let lane;
  if (e.type === 'key') {
    lane = {ArrowLeft:0, KeyA:0, ArrowDown:1, KeyS:1, ArrowRight:2, KeyD:2}[e.key];
  } else if (e.type === 'tap') {
    lane = Math.min(2,Math.floor(e.x*3));
    const box = postbox(lane);
    if (e.x < box.x || e.x > box.x+box.w || e.y < box.y || e.y > box.y+box.h) return s;
  }
  if (lane === undefined) return s;
  s.lastAt = s.elapsed; s.lastLane = lane;
  s.correct = lane === destination(L.content.items[s.hits]);
  if (s.correct) {
    s.hits++;
    s.score += 10;
    if (s.hits === L.quota) s.done = s.won = true;
  } else {
    s.mistakes++;
    if (s.mistakes === 3) s.done = true;
  }
  return s;
}

function witness(s,L) {
  const box = postbox(destination(L.content.items[s.hits]));
  return {type:'tap',x:box.x+box.w/2,y:box.y+box.h/2};
}

function draw(s,L) {
  const out = [];
  const rect = (x,y,w,h,color) => out.push({kind:'rect',x,y,w,h,color});
  const line = (x,y,x2,y2,color) => out.push({kind:'line',x,y,x2,y2,color});
  const polygon = (x,y,points,color) => out.push({kind:'polygon',x,y,points,color});
  const text = (x,y,value,size,color) => out.push({kind:'text',x,y,text:value,size,color});
  const ink = '#233E36', paper = '#F9EDCA', rust = '#9A452E', wood = '#744B36';
  const chapter = L.chapter.number;
  const sky = ['#E9DBAC','#E6CBAD','#C8D6CF'][chapter-1];
  const hills = ['#91A599','#A59E90','#819DA1'][chapter-1];
  rect(0,0,1,1,sky);
  out.push({kind:'circle',x:.86,y:.25,r:.10,color:'#E6A06C'});
  polygon(0,0,[[0,.48],[.12,.28],[.20,.35],[.31,.18],[.44,.43],[.52,.31],
    [.63,.45],[.77,.22],[.88,.35],[.96,.28],[1,.34],[1,.70],[0,.70]],hills);
  polygon(0,0,[[0,.43],[.14,.52],[.28,.40],[.42,.54],[.53,.43],[.72,.57],
    [.86,.40],[1,.45],[1,.72],[0,.72]],'#55746B');
  for (const [x,y,h] of [[.052,.58,.16],[.085,.58,.22],[.16,.60,.14],[.89,.57,.19],[.94,.59,.24]]) {
    polygon(x,y,[[-h*.20,0],[0,-h],[h*.20,0]],'#385B50');
  }
  rect(0,.59,1,.41,'#C69B6F');
  rect(0,.605,1,.021,wood);
  const age = s.elapsed-s.lastAt;
  const shake = !s.correct && age<.42 ? .012*Math.sin(age*60)*(1-age/.42) : 0;
  const x = .5+shake, y=.315;
  const item = L.content.items[Math.min(s.hits,L.quota-1)];
  out.push({kind:'sprite',asset:'envelope',x,y,r:.36});
  rect(x-.09,y-.045,.18,.138,paper);
  text(x,y+.051,(item[0]+1)+' 号站',.095,ink);
  const transfer = item[1]===1 ? '右移一站 →' : item[1]===-1 ? '← 左移一站' : '直达';
  rect(x-.15,y+.118,.30,.08,ink);
  text(x,y+.174,transfer,.046,paper);
  text(.13,.108,'已投 '+s.hits+' / '+L.quota,.05,ink);
  text(.855,.108,'可错 '+Math.max(0,2-s.mistakes)+' 次',.048,ink);
  const stationColors = ['#3C6962','#9C573E','#556575'];
  for (let i=0;i<3;i++) {
    const b=postbox(i), cx=b.x+b.w/2;
    rect(b.x,b.y,b.w,b.h,'#614631');
    rect(b.x+.009,b.y+.008,b.w-.018,b.h-.028,stationColors[i]);
    rect(b.x+.022,b.y+.037,b.w-.044,.025,'#283932');
    text(cx,b.y+.177,String(i+1)+' 号站',.072,paper);
    if (i===s.lastLane && age<.6) {
      rect(b.x+.012,b.y+b.h-.02,b.w-.024,.018,s.correct?'#ECDD8F':'#F1A38B');
    }
  }
  const footer = !s.correct && age<.9 ? '错投 · 同一封信可以重投' :
    chapter===1 ? '看信封上的站号，点对应投递口' : chapter===2 ?
    '右移一站 · 3 号站的下一站是 1 号' : '按箭头左右换站，站点可以首尾相接';
  text(.5,.962,footer,.046,ink);
  if (s.done) {
    rect(.21,.233,.58,.245,paper);
    line(.24,.252,.76,.252,wood);
    text(.5,.35,s.won?'本趟投递完成':s.mistakes>=3?'错投次数已满':'末班邮车已离站',.072,s.won?ink:rust);
    text(.5,.425,'投妥 '+s.hits+' 件 · 错投 '+s.mistakes+' 次',.046,wood);
  }
  return out;
}
