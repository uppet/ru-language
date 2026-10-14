  // Browser-only graphics and resource accounting. No DOM or ambient I/O.
  const browserTypes = {
    helpers: builtin('如观工具', [], 'helpers', 'graphicsKind'),
    canvas: builtin('如观画布', [], 'canvas', 'graphicsKind')
  };
  builtins.values.__如观 = new Instance(browserTypes.helpers,dict());
  let browserCanvas = null, browserSteps = 0, browserOutputBytes = 0;
  const browserEncoder = new TextEncoder();
  function browserReset(){browserSteps=0;browserOutputBytes=0;}
  function browserTick(m,loc){if(++browserSteps>500000)fail(m,'浏览器 JS 执行超过 500000 步预算；请简化代码后重跑',loc);}
  function browserOutput(m,text,loc){
    browserOutputBytes+=browserEncoder.encode(text).length;
    if(browserOutputBytes>262144)fail(m,'浏览器 JS 单次输出超过 256 KiB',loc);
    __ruHost.emit({type:'output',stream:'stdout',text});
  }
  function browserClose(){
    if(!browserCanvas)return;
    const c=browserCanvas;c.closed=true;c.running=false;c.callbacks=dict();c.commands=[];browserResetDrawing(c);browserCanvas=null;
    __ruHost.emit({type:'graphics_closed',canvas_id:c.id});
  }
  const browserIdentity=()=>[1,0,0,1,0,0];
  function browserResetDrawing(c){c.transform=browserIdentity();c.clips=[];c.stack=[];}
  function browserFlush(){
    const c=browserCanvas;if(!c)return;
    if(c.stack.length){const saved=c.stack[0];browserClose();fail(saved.m,'保存与恢复须配对；绘制结束时仍有未恢复的状态',saved.loc);}
    if(!c.dirty)return;
    __ruHost.emit({type:'graphics',canvas_id:c.id,width:c.width,height:c.height,fps:c.fps,running:c.running,handlers:Object.keys(c.callbacks),commands:c.commands.slice()});c.dirty=false;
  }
  const browserEvents={每帧:['frame',1],鼠标按下:['mouse_down',3],鼠标松开:['mouse_up',3],鼠标移动:['mouse_move',2],按键:['key_down',1],松键:['key_up',1]};
  const browserParams={背景:['色'],填色:['色'],描边:['色'],线宽:['粗'],字号:['大小'],矩形:['横','纵','宽','高'],椭圆:['横','纵','宽','高'],线:['横一','纵一','横二','纵二'],文字:['文','横','纵'],三角形:['横一','纵一','横二','纵二','横三','纵三'],多边形:['点阵'],平移:['横','纵'],旋转:['弧度'],缩放:['横倍率','纵倍率'],保存:[],恢复:[],变换:['a','b','c','d','e','f'],重置变换:[],裁剪:['横','纵','宽','高'],取消裁剪:[],帧率:['率'],停:[],继续:[],关闭:[],宽:[],高:[],帧:[]};
  for(const name of Object.keys(browserEvents))browserParams[name]=['回调'];
  function browserMember(m,receiver,name,args,loc){
    const kind=receiver.type.graphicsKind;if(!kind)return MISSING;
    const bad=message=>fail(m,message,loc);
    const num=(value,label,low=-100000,high=100000,integer=false)=>{
      if(typeof value!=='number'||!Number.isFinite(value)||value<low||value>high||(integer&&!Number.isInteger(value)))bad(label+'须为范围内'+(integer?'整数':'有限数'));
      return value;
    };
    const color=(value,optional=false)=>{if(optional&&value===null)return '';if(typeof value!=='string'||![7,9].includes(value.length)||!/^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$/.test(value))bad('颜色须为 #RRGGBB 或 #RRGGBBAA 文字');return value.toLowerCase();};
    if(kind==='helpers'){
      if(name==='颜色'){
        const channels=['红','绿','蓝','不透明度'],a=argsBind(m,name,args,channels,loc);
        const value='#'+channels.map(key=>num(a[key],key,0,255,true).toString(16).padStart(2,'0')).join('');
        m.lastMemberProcedure=false;return value;
      }
      if(name!=='画布')bad('未知如观工具成员：'+name);
      const a=argsBind(m,name,args,['宽','高'],loc),width=num(a.宽,'宽',1,2048,true),height=num(a.高,'高',1,2048,true);
      browserClose();
      browserCanvas={id:Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join(''),width,height,callbacks:dict(),commands:[],bytes:2,fill:'#4677ff',stroke:'#202530',lineWidth:1,textSize:16,fps:30,frame:0,running:false,closed:false,dirty:true,transform:browserIdentity(),clips:[],stack:[]};
      const value=new Instance(browserTypes.canvas,dict());value.graphicsCanvas=browserCanvas;m.lastMemberProcedure=false;return value;
    }
    const c=receiver.graphicsCanvas;
    if(!c||c.closed||c!==browserCanvas)bad('如观画布已关闭；请重新创建画布');
    if(!own(browserParams,name))bad('未知如观画布成员：'+name);
    const a=argsBind(m,name,args,browserParams[name],loc);
    m.lastMemberProcedure=!['宽','高','帧'].includes(name);
    const command=value=>{
      if(value.op!=='background'){
        if(c.transform.some((v,i)=>v!==browserIdentity()[i]))value.transform=c.transform.slice();
        if(c.clips.length)value.clips=c.clips.map(clip=>({...clip,transform:clip.transform.slice()}));
      }
      const size=browserEncoder.encode(JSON.stringify(value)).length+1;
      if(c.commands.length>=2048||c.bytes+size>261120)bad('如观每帧最多 2048 个绘制命令、256 KiB 数据');
      c.commands.push(value);c.bytes+=size;c.dirty=true;
    };
    const multiply=right=>{
      const [a,b,d,e,f,g]=c.transform,[h,i,j,k,l,n]=right;
      const next=[a*h+d*i,b*h+e*i,a*j+d*k,b*j+e*k,a*l+d*n+f,b*l+e*n+g];
      next.forEach(value=>num(value,'累计变换'));c.transform=next;
    };
    if(own(browserEvents,name)){
      const [event,count]=browserEvents[name],fn=a.回调;
      if(!(fn instanceof Fn)||fn.params.length!==count)bad(name+'需要接受 '+count+' 个参数的算／作回调');
      c.callbacks[event]={fn,m,loc};if(event==='frame')c.running=true;
    }else if(name==='宽')return c.width;
    else if(name==='高')return c.height;
    else if(name==='帧')return c.frame;
    else if(name==='关闭'){c.stack=[];browserFlush();browserClose();return null;}
    else if(name==='停'||name==='继续')c.running=name==='继续'&&own(c.callbacks,'frame');
    else if(name==='帧率')c.fps=num(a.率,'帧率',1,60,true);
    else if(name==='填色'||name==='描边')c[name==='填色'?'fill':'stroke']=color(a.色,true);
    else if(name==='线宽'||name==='字号')c[name==='线宽'?'lineWidth':'textSize']=num(a[name==='线宽'?'粗':'大小'],name,1,256);
    else if(name==='保存'){
      if(c.stack.length>=64)bad('保存状态最多 64 层');
      c.stack.push({m,loc,fill:c.fill,stroke:c.stroke,lineWidth:c.lineWidth,textSize:c.textSize,transform:c.transform.slice(),clips:c.clips.map(clip=>({...clip,transform:clip.transform.slice()}))});
    }
    else if(name==='恢复'){
      if(!c.stack.length)bad('恢复须先有配对的保存');
      const {m:module,loc:location,...state}=c.stack.pop();Object.assign(c,state);
    }
    else if(name==='重置变换')c.transform=browserIdentity();
    else if(name==='取消裁剪')c.clips=[];
    else if(name==='平移')multiply([1,0,0,1,num(a.横,'横'),num(a.纵,'纵')]);
    else if(name==='缩放')multiply([num(a.横倍率,'横倍率'),0,0,num(a.纵倍率,'纵倍率'),0,0]);
    else if(name==='旋转'){const angle=num(a.弧度,'弧度'),cos=Math.cos(angle),sin=Math.sin(angle);multiply([cos,sin,-sin,cos,0,0]);}
    else if(name==='变换')multiply(['a','b','c','d','e','f'].map(key=>num(a[key],key)));
    else if(name==='裁剪'){
      if(c.clips.length>=32)bad('裁剪最多 32 层');
      c.clips.push({x:num(a.横,'横'),y:num(a.纵,'纵'),width:num(a.宽,'宽',0),height:num(a.高,'高',0),transform:c.transform.slice()});
    }
    else if(name==='三角形'||name==='多边形'){
      const points=name==='三角形'?[[a.横一,a.纵一],[a.横二,a.纵二],[a.横三,a.纵三]]:a.点阵;
      if(!Array.isArray(points)||points.length<3||points.length>256)bad('多边形点阵须为含 3 至 256 个点的阵');
      const copy=points.map(point=>{if(!Array.isArray(point)||point.length!==2)bad('多边形每个点须为两个坐标的阵');return point.map(value=>num(value,'多边形坐标'));});
      command({op:'polygon',points:copy,fill:c.fill,stroke:c.stroke,stroke_width:c.lineWidth});
    }
    else if(name==='背景'){const value=color(a.色);c.commands=[];c.bytes=2;command({op:'background',color:value});}
    else if(name==='矩形'||name==='椭圆')command({op:name==='矩形'?'rect':'ellipse',x:num(a.横,'横'),y:num(a.纵,'纵'),width:num(a.宽,'宽',0),height:num(a.高,'高',0),fill:c.fill,stroke:c.stroke,stroke_width:c.lineWidth});
    else if(name==='线')command({op:'line',x1:num(a.横一,'横一'),y1:num(a.纵一,'纵一'),x2:num(a.横二,'横二'),y2:num(a.纵二,'纵二'),color:c.stroke,width:c.lineWidth});
    else if(name==='文字'){
      if(typeof a.文!=='string'||Array.from(a.文).length>4096)bad('文字须为不超过 4096 字符的句');
      command({op:'text',x:num(a.横,'横'),y:num(a.纵,'纵'),text:a.文,color:c.fill,size:c.textSize});
    }
    c.dirty=true;return null;
  }
  function browserDispatch(request){
    const c=browserCanvas;
    if(!c||!request||request.canvas_id!==c.id)throw new Error('如观画布已关闭或事件已失效');
    const event=request.event;
    if(!event||typeof event.type!=='string')throw new Error('无效如观事件');
    if(event.type==='close'){browserClose();return;}
    const callback=c.callbacks[event.type];
    if(!callback||(event.type==='frame'&&!c.running))throw new Error('如观事件未启用');
    const {fn,m,loc}=callback;
    let values;
    if(event.type==='frame')values=[++c.frame];
    else if(event.type==='key_down'||event.type==='key_up'){
      if(typeof event.key!=='string'||Array.from(event.key).length>64)fail(m,'无效如观按键',loc);values=[event.key];
    }else{
      if(!Number.isFinite(event.x)||!Number.isFinite(event.y)||Math.abs(event.x)>100000||Math.abs(event.y)>100000)fail(m,'无效如观鼠标坐标',loc);
      values=[event.x,event.y];
      if(event.type!=='mouse_move'){if(!Number.isInteger(event.button)||event.button<0||event.button>2)fail(m,'无效如观鼠标键',loc);values.push(event.button);}
    }
    const previous=c.commands,previousBytes=c.bytes;c.commands=[];c.bytes=2;
    browserReset();browserResetDrawing(c);
    try{
      call(m,fn,values.map(value=>[null,value]),loc);
      if(browserCanvas===c&&!c.closed){
        if(event.type!=='frame'&&!c.commands.length){c.commands=previous;c.bytes=previousBytes;}
        c.dirty=true;
      }
      browserFlush();
    }catch(error){browserClose();throw error;}
  }
