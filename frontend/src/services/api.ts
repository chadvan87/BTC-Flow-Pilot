const base=(import.meta as unknown as {env:Record<string,string>}).env.VITE_API_URL || '';
export async function api<T=any>(path:string,method='GET',payload?:unknown):Promise<T>{
 const r=await fetch(base+'/api'+path,{method,credentials:'include',headers:{'Content-Type':'application/json','X-Flowpilot-Request':'1'},body:payload===undefined?undefined:JSON.stringify(payload)});
 const data=await r.json();
 if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
 return data;
}
