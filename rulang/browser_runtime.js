  // Browser-only graphics and resource accounting. No DOM or ambient I/O.
  const browserTypes = {
    helpers: builtin('如观工具', [], 'helpers', 'graphicsKind'),
    canvas: builtin('如观画布', [], 'canvas', 'graphicsKind'),
    recorder: builtin('如观绘图目标', [], 'recorder', 'graphicsKind'),
    image: builtin('如观图像', [], 'image', 'graphicsKind')
  };
  builtins.values.__如观 = new Instance(browserTypes.helpers,dict());
  let browserCanvas = null, browserSteps = 0, browserOutputBytes = 0;
  let browserPhase='initialization',browserRecording=null;
  const browserEncoder = new TextEncoder();
  // Host-only clock injection; direct module users fall back to the platform's
  // monotonic clock. Neither the function nor timestamps enter the Ru scope.
  const browserNowSeconds=own(__ruHost,'nowSeconds')?__ruHost.nowSeconds:()=>performance.now()/1000;
  // 测文协议：宿主可注入真实字度表与实测钩；缺省与如UI 早期近似度量逐位一致。
  const browserHostFail=message=>{throw new Error(message)};
  const browserDefaultTextMetrics=Object.freeze({全:1,半:0.56,行:1.5});
  let browserTextMetrics=null,browserTextMeasurer=null;
  if(own(__ruHost,'textMetrics')&&__ruHost.textMetrics!==undefined&&__ruHost.textMetrics!==null){
    const injected=__ruHost.textMetrics;
    if(typeof injected!=='object')browserHostFail('textMetrics 须为含全／半／行的对象');
    const resolved={};
    for(const key of ['全','半','行']){
      const value=injected[key];
      if(typeof value!=='number'||!Number.isFinite(value)||value<0.1||value>10)
        browserHostFail('textMetrics.'+key+' 须为 0.1 至 10 之间有限数');
      resolved[key]=value;
    }
    browserTextMetrics=Object.freeze(resolved);
  }
  if(own(__ruHost,'textMeasurer')&&__ruHost.textMeasurer!==undefined&&__ruHost.textMeasurer!==null){
    if(typeof __ruHost.textMeasurer!=='function')browserHostFail('textMeasurer 须为函数');
    browserTextMeasurer=__ruHost.textMeasurer;
  }
  let browserLastClockSample=null;
  function browserSampleTime(m,loc,closeOnError=true){
    let sample;
    try{
      sample=browserNowSeconds();
      if(typeof sample!=='number'||!Number.isFinite(sample)||sample<0||
          (browserLastClockSample!==null&&sample<browserLastClockSample))throw new Error();
    }catch(error){
      if(closeOnError)browserClose();
      fail(m,'如观宿主单调时钟无效；请重新运行',loc);
    }
    browserLastClockSample=sample;return sample;
  }
  function browserSetRunning(c,running){
    if(running&&!c.running)c.previousFrame=null;
    c.running=running;
  }
  function browserReset(){browserSteps=0;browserOutputBytes=0;}
  function browserTick(m,loc){if(++browserSteps>500000)fail(m,`浏览器 JS 执行超过 500000 步预算（实际 ${browserSteps} 步，阈值 500000 步）；请简化代码后重跑`,loc);}
  function browserOutput(m,text,loc){
    browserOutputBytes+=browserEncoder.encode(text).length;
    if(browserOutputBytes>262144)fail(m,'浏览器 JS 单次输出超过 256 KiB',loc);
    __ruHost.emit({type:'output',stream:'stdout',text});
  }
  function browserClose(){
    if(!browserCanvas)return;
    const c=browserCanvas;c.closed=true;c.running=false;c.callbacks=dict();browserResetCommands(c);c.resources.clear();c.resourceSizes.clear();c.resourcePixels=0;c.resourceBytes=2;browserResetDrawing(c);browserCanvas=null;
    __ruHost.emit({type:'graphics_closed',canvas_id:c.id});
  }
  const browserIdentity=()=>[1,0,0,1,0,0];
  function browserResetCommands(c){
    c.commands=[];c.bytes=2;c.referenceIds=new Set();c.referenceBytes=0;c.referenceCommands=0;
  }
  function browserResetDrawing(c){c.transform=browserIdentity();c.clips=[];c.stack=[];}
  function browserFlush(){
    const c=browserCanvas;if(!c)return;
    if(c.stack.length){const saved=c.stack[0];browserClose();fail(saved.m,'保存与恢复须配对；绘制结束时仍有未恢复的状态',saved.loc);}
    if(!c.dirty)return;
    const scene=browserScene(c,c.commands);browserCheckScene(c,scene,c.module,c.location);
    __ruHost.emit(scene);c.dirty=false;
  }
  function browserResources(c,commands){
    const ids=new Set(commands.filter(command=>command.op==='image').map(command=>command.resource));
    return Array.from(ids,id=>c.resources.get(id));
  }
  function browserScene(c,commands){
    const scene={type:'graphics',canvas_id:c.id,width:c.width,height:c.height,fps:c.fps,running:c.running,handlers:Object.keys(c.callbacks),commands:commands.slice()};
    const resources=browserResources(c,commands);if(resources.length)scene.resources=resources;
    return scene;
  }
  function browserCheckScene(c,scene,m,loc){
    const resources=scene.resources||[];
    if(scene.commands.length+resources.reduce((n,r)=>n+r.commands.length,0)>2048)fail(m,'如观每帧根命令与引用缓存合计最多 2048 个绘制命令',loc);
    if(browserEncoder.encode(JSON.stringify(scene)).length>262144)fail(m,'如观完整画面含缓存超过 256 KiB 数据',loc);
  }
  function browserCheckCommand(c,value,size,m,loc){
    const added=value.op==='image'&&!c.referenceIds.has(value.resource);
    const recipe=added?c.resources.get(value.resource):null;
    const count=c.referenceCommands+(added?recipe.commands.length:0);
    if(c.commands.length+1+count>2048)fail(m,'如观每帧根命令与引用缓存合计最多 2048 个绘制命令',loc);
    const references=c.referenceIds.size+(added?1:0);
    const bytes=c.referenceBytes+(added?c.resourceSizes.get(value.resource):0);
    if(references){
      // Only metadata is serialized here. Recipes are encoded once on creation;
      // the actual complete event is still measured independently at flush.
      const base=browserEncoder.encode(JSON.stringify(browserScene(c,[]))).length;
      const total=base+c.bytes+size-3+',"resources":'.length+2+references-1+bytes;
      if(total>262144)fail(m,'如观完整画面含缓存超过 256 KiB 数据',loc);
    }
    if(added){c.referenceIds.add(value.resource);c.referenceBytes=bytes;c.referenceCommands=count;}
  }
  function browserFreeze(value){
    if(value&&typeof value==='object'){Object.values(value).forEach(browserFreeze);Object.freeze(value);}return value;
  }
  function browserDrawingTarget(width,height){
    return {width,height,commands:[],bytes:2,fill:'#4677ff',stroke:'#202530',lineWidth:1,textSize:16,textAlign:'left',textBaseline:'top',transform:browserIdentity(),clips:[],stack:[],dirty:false,closed:false};
  }
  const browserEvents={每帧:['frame',1],鼠标按下:['mouse_down',3],鼠标松开:['mouse_up',3],鼠标移动:['mouse_move',2],触下:['touch_start',3],触移:['touch_move',3],触松:['touch_end',3],改尺寸:['resize',2],按键:['key_down',1],松键:['key_up',1],图就绪:['image_ready',3],图失败:['image_failed',2],件就绪:['file_ready',2],件失败:['file_failed',2],键按下:['text_key',1],字符:['text_char',1],剪贴:['text_paste',1],组开始:['text_comp_start',0],组更新:['text_comp_update',2],组结束:['text_comp_end',1],服务回:['service_response',4],服务告:['service_ad',1]};
  const browserTextKeys=new Set(['退格','删除','左','右','上','下','家','终','回车','空格','跳格','逃脱']);
  const browserParams={背景:['色'],填色:['色'],描边:['色'],线宽:['粗'],字号:['大小'],文字对齐:['横向','纵向'],矩形:['横','纵','宽','高'],椭圆:['横','纵','宽','高'],线:['横一','纵一','横二','纵二'],文字:['文','横','纵'],三角形:['横一','纵一','横二','纵二','横三','纵三'],多边形:['点阵'],平移:['横','纵'],旋转:['弧度'],缩放:['横倍率','纵倍率'],保存:[],恢复:[],变换:['a','b','c','d','e','f'],重置变换:[],裁剪:['横','纵','宽','高'],取消裁剪:[],帧率:['率'],停:[],继续:[],关闭:[],宽:[],高:[],帧:[],经过秒:[],间隔秒:[]};
  for(const name of Object.keys(browserEvents))browserParams[name]=['回调'];
  browserParams.缓存=['宽','高','绘制'];
  browserParams.贴图=['图像','横','纵'];
  browserParams.图请求=['号','源'];
  browserParams.绘图=['号','横','纵','宽','高'];
  browserParams.图释放=['号'];
  browserParams.件请求=['号','源','式'];
  browserParams.服务请=['号','服务','操作','径','文','旗'];
  browserParams.尺寸=['宽','高'];
  browserParams.入焦点=['横','纵','宽','高','文','标'];
  browserParams.入失焦=[];
  browserParams.入更新=['文','标'];
  browserParams.字度=[];
  browserParams.测文=['文'];
  const browserRecorderForbidden=new Set(['缓存','贴图','图请求','绘图','图释放','件请求','入焦点','入失焦','入更新','字度','测文','帧率','停','继续','关闭','帧','经过秒','间隔秒','尺寸',...Object.keys(browserEvents)]);
  browserParams.弧=['横','纵','宽','高','始角','转角'];
  browserParams.扇形=['横','纵','宽','高','始角','转角'];
  browserParams.折线=['点阵'];
  browserParams.贝塞尔=['起横','起纵','控一横','控一纵','控二横','控二纵','终横','终纵'];
  const browserTextAligns=Object.freeze({左:'left',中:'center',右:'right'});
  const browserTextBaselines=Object.freeze({上:'top',中:'middle',下:'bottom',基线:'alphabetic'});
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
      if(browserRecording)bad('缓存录制期间不能创建或替换主画布');
      const a=argsBind(m,name,args,['宽','高'],loc),width=num(a.宽,'宽',1,2048,true),height=num(a.高,'高',1,2048,true);
      const origin=browserSampleTime(m,loc,false);
      browserClose();
      browserCanvas={id:Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join(''),width,height,callbacks:dict(),commands:[],bytes:2,fill:'#4677ff',stroke:'#202530',lineWidth:1,textSize:16,textAlign:'left',textBaseline:'top',fps:30,frame:0,origin,elapsed:0,delta:0,previousFrame:null,running:false,closed:false,dirty:true,transform:browserIdentity(),clips:[],stack:[],resources:new Map(),resourceSizes:new Map(),resourcePixels:0,resourceBytes:2,referenceIds:new Set(),referenceBytes:0,referenceCommands:0,imageLoads:new Set(),fileLoads:new Set(),loadDone:new Set(),servicePending:[],serviceAdSent:false,metrics:{...(browserTextMetrics||browserDefaultTextMetrics)},token:{},module:m,location:loc};
      const value=new Instance(browserTypes.canvas,dict());value.graphicsCanvas=browserCanvas;m.lastMemberProcedure=false;return value;
    }
    if(kind==='image'){
      if(name!=='宽'&&name!=='高')bad('如观图像只支持宽、高查询');
      argsBind(m,name,args,[],loc);m.lastMemberProcedure=false;return receiver.graphicsImage[name==='宽'?'width':'height'];
    }
    const c=receiver.graphicsCanvas;
    if(kind==='recorder'){
      if(!c||c.closed||c!==browserRecording)bad('如观缓存绘图目标已失效');
      if(browserRecorderForbidden.has(name))bad('缓存绘图目标不支持成员：'+name);
    }else{
      if(!c||c.closed||c!==browserCanvas)bad('如观画布已关闭；请重新创建画布');
      if(browserRecording&&!['宽','高','帧','经过秒','间隔秒'].includes(name))bad('缓存录制期间不能修改主画布');
    }
    if(!own(browserParams,name))bad('未知如观画布成员：'+name);
    const a=argsBind(m,name,args,browserParams[name],loc);
    m.lastMemberProcedure=!['宽','高','帧','经过秒','间隔秒','字度','测文','缓存'].includes(name);
    const command=value=>{
      if(value.op!=='background'){
        if(c.transform.some((v,i)=>v!==browserIdentity()[i]))value.transform=c.transform.slice();
        if(c.clips.length)value.clips=c.clips.map(clip=>({...clip,transform:clip.transform.slice()}));
      }
      const size=browserEncoder.encode(JSON.stringify(value)).length+1;
      if(c.commands.length>=2048||c.bytes+size>261120)bad('如观每帧最多 2048 个绘制命令、256 KiB 数据');
      if(kind==='recorder'){
        if(c.commands.length>=2047)bad('单份缓存最多 2047 个命令，须为贴图预留一条命令');
        // bytes includes one trailing-comma allowance; remove it for exact
        // resource/list accounting without serializing the whole prefix again.
        const recipeBytes=c.recipeBaseBytes+c.bytes+size-3;
        if(browserCanvas.resourceBytes+recipeBytes+(browserCanvas.resources.size?1:0)>131072)bad('如观全部缓存配方最多 128 KiB 数据');
      }else if(c.resources.size)browserCheckCommand(c,value,size,m,loc);
      c.commands.push(value);c.bytes+=size;c.dirty=true;
    };
    const multiply=right=>{
      const [a,b,d,e,f,g]=c.transform,[h,i,j,k,l,n]=right;
      const next=[a*h+d*i,b*h+e*i,a*j+d*k,b*j+e*k,a*l+d*n+f,b*l+e*n+g];
      next.forEach(value=>num(value,'累计变换'));c.transform=next;
    };
    if(name==='缓存'){
      if(browserPhase!=='initialization')bad('缓存只可在初始化时创建，不能在事件回调中创建');
      const width=num(a.宽,'缓存宽',1,2048,true),height=num(a.高,'缓存高',1,2048,true),fn=a.绘制;
      if(!(fn instanceof Fn)||fn.params.length!==1)bad('缓存绘制需要接受 1 个参数的算／作回调');
      if(c.resources.size>=8)bad('如观每画布最多 8 份缓存');
      if(c.resourcePixels+width*height>4194304)bad('如观全部缓存最多 4194304 像素');
      const target=browserDrawingTarget(width,height),id='cache-'+(c.resources.size+1);
      target.resourceId=id;target.recipeBaseBytes=browserEncoder.encode(JSON.stringify({id,kind:'drawing',width,height,commands:[]})).length;
      if(c.resourceBytes+target.recipeBaseBytes+(c.resources.size?1:0)>131072)bad('如观全部缓存配方最多 128 KiB 数据');
      const temporary=new Instance(browserTypes.recorder,dict());temporary.graphicsCanvas=target;
      browserRecording=target;
      try{
        call(m,fn,[[null,temporary]],loc);
        if(target.stack.length)bad('缓存保存与恢复须配对');
        const recipe=browserFreeze(JSON.parse(JSON.stringify({id,kind:'drawing',width,height,commands:target.commands})));
        const bytes=browserEncoder.encode(JSON.stringify([...c.resources.values(),recipe])).length;
        if(bytes>131072)bad('如观全部缓存配方最多 128 KiB 数据');
        c.resources.set(id,recipe);c.resourceSizes.set(id,browserEncoder.encode(JSON.stringify(recipe)).length);c.resourcePixels+=width*height;c.resourceBytes=bytes;
        const image=new Instance(browserTypes.image,dict());
        image.graphicsImage=Object.freeze({owner:c.id,token:c.token,id,width,height});
        m.lastMemberProcedure=false;return image;
      }finally{
        target.closed=true;target.commands=[];browserResetDrawing(target);temporary.graphicsCanvas=null;browserRecording=null;
      }
    }else if(name==='贴图'){
      const image=a.图像 instanceof Instance&&a.图像.type===browserTypes.image?a.图像.graphicsImage:null;
      if(!image||image.owner!==c.id||image.token!==c.token||!c.resources.has(image.id))bad('贴图须使用当前画布的有效如观图像');
      command({op:'image',resource:image.id,x:num(a.横,'横'),y:num(a.纵,'纵')});
    }else if(name==='图请求'){
      const id=num(a.号,'号',1,10000000,true);
      if(typeof a.源!=='string'||!a.源||browserEncoder.encode(a.源).length>512)bad('如观图像源 须为非空句，最长 512 字节');
      if(!c.imageLoads.has(id)&&c.imageLoads.size>=64)bad('如观图像装载最多 64 项；请用 图释放 归还句柄');
      c.imageLoads.add(id);
      command({op:'image_request',id,source:a.源});
    }else if(name==='绘图'){
      const id=num(a.号,'号',1,10000000,true);
      command({op:'draw_image',id,x:num(a.横,'横'),y:num(a.纵,'纵'),width:num(a.宽,'宽',0),height:num(a.高,'高',0)});
    }else if(name==='图释放'){
      const id=num(a.号,'号',1,10000000,true);
      c.imageLoads.delete(id);
      command({op:'image_release',id});
    }else if(name==='件请求'){
      const id=num(a.号,'号',1,10000000,true);
      if(typeof a.源!=='string'||!a.源||browserEncoder.encode(a.源).length>512)bad('如观文件源 须为非空句，最长 512 字节');
      if(a.式!=='文'&&a.式!=='base64')bad("如观文件模式 只支持 '文' 或 'base64'");
      if(!c.fileLoads.has(id)&&c.fileLoads.size>=64)bad('如观文件装载最多 64 项');
      c.fileLoads.add(id);
      command({op:'file_request',id,source:a.源,mode:a.式});
    }else if(name==='服务请'){
      const id=num(a.号,'号',1,10000000,true);
      if(typeof a.服务!=='string'||!a.服务||browserEncoder.encode(a.服务).length>64)bad('如观服务名 须为非空句，最长 64 字节');
      if(typeof a.操作!=='string'||!a.操作||browserEncoder.encode(a.操作).length>64)bad('如观服务操作 须为非空句，最长 64 字节');
      if(typeof a.径!=='string'||browserEncoder.encode(a.径).length>512)bad('如观服务径 最长 512 字节');
      if(typeof a.文!=='string'||browserEncoder.encode(a.文).length>8388608)bad('如观服务文 最长 8 MiB');
      if(typeof a.旗!=='boolean')bad('如观服务旗 须为真假');
      command({op:'service_request',id,service:a.服务,action:a.操作,path:a.径,text:a.文,flag:a.旗});
      // 网服务双端本地实现（fetch，10 秒超时）：有 fetch 先拦，其余交桥；
      // 无桥不识别者按能力诚实原则自动回失败，与 测文三档 同先例。
      if(a.服务==='网'&&typeof fetch==='function')browserNetRequest(c.id,{id,service:a.服务,action:a.操作,path:a.径,text:a.文,flag:a.旗});
      else if(__ruHost&&typeof __ruHost.handleService==='function')__ruHost.handleService(c.id,{id,service:a.服务,action:a.操作,path:a.径,text:a.文,flag:a.旗});
      else c.servicePending.push({id,service:a.服务});
    }else if(name==='入焦点'){
      if(typeof a.文!=='string'||browserEncoder.encode(a.文).length>8388608)bad('如观文入文本 须为句，最长 8 MiB');
      command({op:'text_focus',x:num(a.横,'横'),y:num(a.纵,'纵'),width:num(a.宽,'宽',0,100000),height:num(a.高,'高',0,100000),text:a.文,cursor:num(a.标,'标',0,4096,true)});
    }else if(name==='入失焦'){
      command({op:'text_blur'});
    }else if(name==='入更新'){
      if(typeof a.文!=='string'||Array.from(a.文).length>4096)bad('如观文入文本 最长 4096 字');
      command({op:'text_update',text:a.文,cursor:num(a.标,'标',0,4096,true),sel:''});
    }else if(own(browserEvents,name)){
      const [event,count]=browserEvents[name],fn=a.回调;
      if(!(fn instanceof Fn)||fn.params.length!==count)bad(name+'需要接受 '+count+' 个参数的算／作回调');
      c.callbacks[event]={fn,m,loc};if(event==='frame')browserSetRunning(c,true);
    }else if(name==='宽')return c.width;
    else if(name==='高')return c.height;
    else if(name==='尺寸'){
      const w=num(a.宽,'宽',1,100000,true),h=num(a.高,'高',1,100000,true);
      c.width=w;c.height=h;c.dirty=true;
      return;
    }
    else if(name==='帧')return c.frame;
    else if(name==='经过秒')return c.elapsed;
    else if(name==='间隔秒')return c.delta;
    else if(name==='字度'){
      const result=new RuMap();
      for(const key of ['全','半','行'])mapPut(m,result,key,c.metrics[key],loc);
      return result;
    }
    else if(name==='测文'){
      const text=a.文;
      if(typeof text!=='string'||Array.from(text).length>4096)bad('测文须为不超过 4096 字符的句');
      if(browserTextMeasurer!==null){
        const width=browserTextMeasurer(text,c.textSize);
        if(typeof width!=='number'||!Number.isFinite(width)||width<0||width>10000000)bad('如观测文宿主返回无效宽度');
        return width;
      }
      let width=0;
      for(const char of text)width+=(char.codePointAt(0)<0x4E00?c.metrics.半:c.metrics.全);
      return width*c.textSize;
    }
    else if(name==='关闭'){c.stack=[];browserFlush();browserClose();return null;}
    else if(name==='停'||name==='继续')browserSetRunning(c,name==='继续'&&own(c.callbacks,'frame'));
    else if(name==='帧率')c.fps=num(a.率,'帧率',1,60,true);
    else if(name==='填色'||name==='描边')c[name==='填色'?'fill':'stroke']=color(a.色,true);
    else if(name==='线宽'||name==='字号')c[name==='线宽'?'lineWidth':'textSize']=num(a[name==='线宽'?'粗':'大小'],name,1,256);
    else if(name==='文字对齐'){
      if(typeof a.横向!=='string'||!own(browserTextAligns,a.横向))bad("文字对齐横向须为 '左'、'中' 或 '右' 的句");
      if(typeof a.纵向!=='string'||!own(browserTextBaselines,a.纵向))bad("文字对齐纵向须为 '上'、'中'、'下' 或 '基线' 的句");
      // Validate both arguments before changing either persistent style.
      c.textAlign=browserTextAligns[a.横向];c.textBaseline=browserTextBaselines[a.纵向];
    }
    else if(name==='保存'){
      if(c.stack.length>=64)bad('保存状态最多 64 层');
      c.stack.push({m,loc,fill:c.fill,stroke:c.stroke,lineWidth:c.lineWidth,textSize:c.textSize,textAlign:c.textAlign,textBaseline:c.textBaseline,transform:c.transform.slice(),clips:c.clips.map(clip=>({...clip,transform:clip.transform.slice()}))});
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
    else if(name==='三角形'||name==='多边形'||name==='折线'){
      const points=name==='三角形'?[[a.横一,a.纵一],[a.横二,a.纵二],[a.横三,a.纵三]]:a.点阵;
      const minimum=name==='折线'?2:3;
      if(!Array.isArray(points)||points.length<minimum||points.length>256)bad(name+'点阵须为含 '+minimum+' 至 256 个点的阵');
      const copy=Array.from(points,(point,index)=>{if(!own(points,index)||!Array.isArray(point)||point.length!==2||!own(point,0)||!own(point,1))bad(name+'每个点须为两个坐标的阵');return Array.from(point,value=>num(value,name+'坐标'));});
      command({op:name==='折线'?'polyline':'polygon',points:copy,fill:name==='折线'?'':c.fill,stroke:c.stroke,stroke_width:c.lineWidth});
    }
    else if(name==='背景'){
      const value=color(a.色);
      // 背景重置整帧绘制，但装载管理命令（image_request/file_request/
      // image_release）不是绘制，须在重置后存活（与 Python 宿主一致）。
      const kept=c.commands.filter(command=>command.op==='image_request'||command.op==='file_request'||command.op==='image_release');
      browserResetCommands(c);
      kept.forEach(command);
      command({op:'background',color:value});
    }
    // Invisible/zero-sweep drawing calls still replace input scenes and spend
    // command/byte budget. Native rendering alone interprets the signed sweep.
    else if(name==='弧'||name==='扇形')command({op:name==='弧'?'arc':'sector',x:num(a.横,'横'),y:num(a.纵,'纵'),width:num(a.宽,'宽',0),height:num(a.高,'高',0),start:num(a.始角,'始角'),sweep:num(a.转角,'转角'),fill:name==='弧'?'':c.fill,stroke:c.stroke,stroke_width:c.lineWidth});
    else if(name==='矩形'||name==='椭圆')command({op:name==='矩形'?'rect':'ellipse',x:num(a.横,'横'),y:num(a.纵,'纵'),width:num(a.宽,'宽',0),height:num(a.高,'高',0),fill:c.fill,stroke:c.stroke,stroke_width:c.lineWidth});
    else if(name==='贝塞尔')command({op:'bezier',x1:num(a.起横,'起横'),y1:num(a.起纵,'起纵'),cx1:num(a.控一横,'控一横'),cy1:num(a.控一纵,'控一纵'),cx2:num(a.控二横,'控二横'),cy2:num(a.控二纵,'控二纵'),x2:num(a.终横,'终横'),y2:num(a.终纵,'终纵'),fill:'',stroke:c.stroke,stroke_width:c.lineWidth});
    else if(name==='线')command({op:'line',x1:num(a.横一,'横一'),y1:num(a.纵一,'纵一'),x2:num(a.横二,'横二'),y2:num(a.纵二,'纵二'),color:c.stroke,width:c.lineWidth});
    else if(name==='文字'){
      if(typeof a.文!=='string'||Array.from(a.文).length>4096)bad('文字须为不超过 4096 字符的句');
      const text={op:'text',x:num(a.横,'横'),y:num(a.纵,'纵'),text:a.文,color:c.fill,size:c.textSize};
      // Missing fields are frozen left/top defaults, including in old scenes.
      if(c.textAlign!=='left')text.align=c.textAlign;
      if(c.textBaseline!=='top')text.baseline=c.textBaseline;
      command(text);
    }
    c.dirty=true;return null;
  }
  function browserDeliverServiceMail(){
    // 宿主服务通道：广告在 服务告 绑定后投递一次（无桥＝空表）；无桥宿主的
    // 服务请求按能力诚实原则自动回失败，与当前事件同批投递（先于其回调）。
    const c=browserCanvas;
    if(!c||c.closed)return;
    // 网服务：取（GET）/投（POST 附文）；回执异步经事件投递（fetch 回调），
    // 与宿主桥回执同一事件形状。错误按能力诚实原则原文回失败。
    if(!c.serviceAdSent&&c.callbacks.service_ad){
      c.serviceAdSent=true;
      const list=(typeof __ruHost==='object'&&__ruHost&&typeof __ruHost.services==='function')?__ruHost.services():[];
      const merged=Array.isArray(list)?list.slice():[];
      if(typeof fetch==='function'&&merged.indexOf('网')<0)merged.push('网');
      browserDispatch({canvas_id:c.id,event:{type:'service_ad',services:merged.join(' ')}});
    }
    while(c.servicePending.length){
      const pending=c.servicePending.shift();
      browserDispatch({canvas_id:c.id,event:{type:'service_response',id:pending.id,ok:false,value:null,error:'宿主无此服务：'+pending.service}});
    }
  }
  function browserNetRequest(canvasId,job){
    const finish=(ok,value,error)=>browserDispatch({canvas_id:canvasId,event:{type:'service_response',id:job.id,ok,value:ok?value:null,error:ok?null:String(error||'网 取文失败').slice(0,512)}});
    const url=job.path;
    if(!url)return finish(false,null,'网 网址不可为空');
    if(!/^https?:\/\//.test(url))return finish(false,null,'网 只识 http/https');
    if(job.action!=='拉'&&job.action!=='投')return finish(false,null,'网 不识此操作：'+job.action);
    const abort=typeof AbortController==='function'?new AbortController():null;
    const timer=abort?setTimeout(()=>abort.abort(),10000):null;
    fetch(url,{
      method:job.action==='投'?'POST':'GET',
      headers:job.action==='投'?{'Content-Type':job.flag?'application/json':'text/plain; charset=utf-8'}:{'Accept':'text/plain, */*;q=0.8'},
      body:job.action==='投'?(job.text||''):undefined,
      signal:abort?abort.signal:undefined,
    }).then(response=>{
      if(!response.ok)throw new Error('网 HTTP '+response.status);
      return response.text();
    }).then(text=>{
      if(timer)clearTimeout(timer);
      if(browserEncoder.encode(text).length>8388608)return finish(false,null,'网 响应超过配额');
      finish(true,text,null);
    }).catch(error=>{
      if(timer)clearTimeout(timer);
      finish(false,null,error&&error.message?error.message:error);
    });
  }

  function browserDispatch(request){
    const c=browserCanvas;
    if(!c||!request||request.canvas_id!==c.id)throw new Error('如观画布已关闭或事件已失效');
    browserDeliverServiceMail();
    if(Object.keys(request).some(key=>!['canvas_id','event'].includes(key)))throw new Error('如观请求含未知字段');
    const event=request.event;
    if(!event||typeof event!=='object'||Array.isArray(event)||
        !['frame','close','mouse_down','mouse_up','mouse_move','touch_start','touch_move','touch_end','resize','key_down','key_up','image_ready','image_failed','file_ready','file_failed','text_key','text_char','text_paste','text_comp_start','text_comp_update','text_comp_end','service_response','service_ad'].includes(event.type))throw new Error('无效如观事件');
    const allowed=['type'];
    if(event.type.startsWith('mouse_'))allowed.push('x','y','button');
    else if(event.type.startsWith('touch_'))allowed.push('id','x','y');
    else if(event.type==='resize')allowed.push('width','height');
    else if(event.type.startsWith('key_'))allowed.push('key');
    else if(event.type==='image_ready')allowed.push('id','width','height');
    else if(event.type==='image_failed'||event.type==='file_failed')allowed.push('id','error');
    else if(event.type==='file_ready')allowed.push('id','text');
    else if(event.type==='text_key')allowed.push('key');
    else if(event.type==='text_char'||event.type==='text_paste'||event.type==='text_comp_end')allowed.push('text');
    else if(event.type==='text_comp_update')allowed.push('text','cursor');
    else if(event.type==='service_response')allowed.push('id','ok','value','error');
    else if(event.type==='service_ad')allowed.push('services');
    if(Object.keys(event).some(key=>!allowed.includes(key)))throw new Error('如观事件含未知字段');
    if(event.type==='close'){browserClose();return;}
    const callback=c.callbacks[event.type];
    const asyncEvent=event.type==='image_ready'||event.type==='image_failed'||event.type==='file_ready'||event.type==='file_failed';
    if(!callback){
      // Readiness nobody listens to is cleanup noise; mouse/key/frame stay strict.
      if(asyncEvent||event.type==='service_response'||event.type==='service_ad')return;
      throw new Error('如观事件未启用');
    }
    if(asyncEvent){
      // 只对真正在途的装载句柄送就绪：未知句柄与重复就绪按噪音忽略。
      // 校验先行（见下），坏事件仍须报错。
      const outstanding=event.type.startsWith('image')?c.imageLoads:c.fileLoads;
      if(!outstanding.has(event.id)||c.loadDone.has(event.id))return;
    }
    if(event.type==='frame'&&!c.running)throw new Error('如观事件未启用');
    const {fn,m,loc}=callback;
    let values;
    if(event.type==='frame')values=[c.frame+1];
    else if(event.type==='key_down'||event.type==='key_up'){
      if(typeof event.key!=='string'||Array.from(event.key).length>64)fail(m,'无效如观按键',loc);values=[event.key];
    }else if(event.type==='image_ready'){
      if(!Number.isInteger(event.id)||event.id<0||event.id>10000000)fail(m,'无效如观装载句柄',loc);
      if(!Number.isInteger(event.width)||event.width<1||event.width>4096||!Number.isInteger(event.height)||event.height<1||event.height>4096)fail(m,'无效如观图像尺寸',loc);
      values=[event.id,event.width,event.height];
    }else if(event.type==='image_failed'||event.type==='file_failed'){
      if(!Number.isInteger(event.id)||event.id<0||event.id>10000000)fail(m,'无效如观装载句柄',loc);
      if(typeof event.error!=='string'||!event.error||browserEncoder.encode(event.error).length>512)fail(m,'无效如观装载错误',loc);
      values=[event.id,event.error];
    }else if(event.type==='file_ready'){
      if(!Number.isInteger(event.id)||event.id<0||event.id>10000000)fail(m,'无效如观装载句柄',loc);
      if(typeof event.text!=='string'||browserEncoder.encode(event.text).length>8388608)fail(m,'无效如观文件内容',loc);
      values=[event.id,event.text];
    }else if(event.type==='text_key'){
      if(typeof event.key!=='string'||!browserTextKeys.has(event.key))fail(m,'无效如观文入键（须为附录 A 编辑键名）',loc);
      values=[event.key];
    }else if(event.type==='text_char'||event.type==='text_paste'){
      if(typeof event.text!=='string'||(event.type==='text_char'?Array.from(event.text).length!==1:(!event.text||Array.from(event.text).length>4096)))fail(m,'无效如观文入文本',loc);
      values=[event.text];
    }else if(event.type==='text_comp_start'){
      values=[];
    }else if(event.type==='text_comp_update'){
      if(typeof event.text!=='string'||Array.from(event.text).length>256)fail(m,'无效如观输入法组合',loc);
      if(!Number.isFinite(event.cursor)||event.cursor<0||event.cursor>256)fail(m,'无效如观输入法光标',loc);
      values=[event.text,event.cursor];
    }else if(event.type==='text_comp_end'){
      if(typeof event.text!=='string'||Array.from(event.text).length>256)fail(m,'无效如观输入法定字',loc);
      values=[event.text];
    }else if(event.type==='service_response'){
      if(!Number.isInteger(event.id)||event.id<0||event.id>10000000)fail(m,'无效如观服务句柄',loc);
      if(typeof event.ok!=='boolean')fail(m,'无效如观服务响应',loc);
      if(event.value!=null&&(typeof event.value!=='string'||browserEncoder.encode(event.value).length>8388608))fail(m,'无效如观服务值',loc);
      if(event.error!=null&&(typeof event.error!=='string'||!browserEncoder.encode(event.error).length||browserEncoder.encode(event.error).length>512))fail(m,'无效如观服务错误',loc);
      values=[event.id,event.ok,event.value==null?'':event.value,event.error==null?'':event.error];
    }else if(event.type==='service_ad'){
      if(typeof event.services!=='string'||browserEncoder.encode(event.services).length>4096)fail(m,'无效如观服务广告',loc);
      values=[event.services];
    }else if(event.type.startsWith('touch_')){
      if(!Number.isInteger(event.id)||event.id<0||event.id>100000)fail(m,'无效如观触屏指针',loc);
      if(!Number.isFinite(event.x)||!Number.isFinite(event.y)||Math.abs(event.x)>100000||Math.abs(event.y)>100000)fail(m,'无效如观触屏坐标',loc);
      values=[event.id,event.x,event.y];
    }else if(event.type==='resize'){
      if(!Number.isInteger(event.width)||event.width<1||event.width>100000||!Number.isInteger(event.height)||event.height<1||event.height>100000)fail(m,'无效如观尺寸',loc);
      values=[event.width,event.height];
    }else{
      if(!Number.isFinite(event.x)||!Number.isFinite(event.y)||Math.abs(event.x)>100000||Math.abs(event.y)>100000)fail(m,'无效如观鼠标坐标',loc);
      values=[event.x,event.y];
      if(own(event,'button')&&(!Number.isInteger(event.button)||event.button<0||event.button>2))fail(m,'无效如观鼠标键',loc);
      if(event.type!=='mouse_move'){
        if(!own(event,'button'))fail(m,'无效如观鼠标键',loc);
        values.push(event.button);
      }
    }
    if(asyncEvent)c.loadDone.add(event.id);
    const now=browserSampleTime(m,loc);
    c.elapsed=now-c.origin;c.delta=event.type==='frame'&&c.previousFrame!==null?now-c.previousFrame:0;
    if(event.type==='frame'){c.previousFrame=now;c.frame++;}
    const previous=c.commands,previousBytes=c.bytes,previousIds=c.referenceIds,previousReferenceBytes=c.referenceBytes,previousReferenceCommands=c.referenceCommands;browserResetCommands(c);
    browserReset();browserResetDrawing(c);
    const previousPhase=browserPhase;browserPhase='event';
    try{
      call(m,fn,values.map(value=>[null,value]),loc);
      if(browserCanvas===c&&!c.closed){
        if(asyncEvent){
          // 装载就绪：旧装帧已作废（源可能已换或行已消失），不恢复不重发；
          // 随后的补帧会全量重绘最新场景。
        }else{
          if(event.type!=='frame'&&!c.commands.length){
            if(event.type!=='service_response'&&event.type!=='service_ad'){
              // Ignored inputs retain the previous complete scene (phase-2
              // contract: re-publish the restored frame). Service mail is
              // internal delivery: silent callbacks stay silent.
              c.commands=previous;c.bytes=previousBytes;c.referenceIds=previousIds;c.referenceBytes=previousReferenceBytes;c.referenceCommands=previousReferenceCommands;
              c.dirty=true;
            }
          }else{
            c.dirty=true;
          }
        }
      }
      browserFlush();
    }catch(error){browserClose();throw error;}finally{browserPhase=previousPhase;}
    if(asyncEvent&&browserCanvas===c&&c.running&&own(c.callbacks,'frame')){
      // 装载就绪视同一次帧推进：库只在每帧回调里绘制，运行时补一帧重渲染
      // （与浏览器宿主就绪后下一拍 rAF 重绘对齐，也与 Python 宿主一致）。
      browserDispatch({canvas_id:c.id,event:{type:'frame'}});
    }
  }
