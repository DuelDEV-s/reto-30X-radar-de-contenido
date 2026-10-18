import test from "node:test";
import assert from "node:assert/strict";
import { filterPosts, postSummary, weeklyPosts } from "../src/discoveryData.ts";

const post = (id, values={}) => ({shortcode:id,username:"cuenta.qa",caption:"Una explicación de agentes",posted_at:"2026-10-12T12:00:00Z",performance:null,views:null,label:"sin_linea_base",content_type:"video",topic_review:null,...values});
const filters = {creator:"",search:"",label:"",format:"",onlyTopic:true,sort:"performance"};

test("summary preserves zero and excludes unknown or non-finite performance from the median",()=>{
  const result=postSummary([post("zero",{performance:0,label:"bajo"}),post("known",{performance:2,label:"sobresaliente"}),post("unknown"),post("invalid",{performance:NaN})]);
  assert.equal(result.pieces,4);
  assert.equal(result.comparable,2);
  assert.equal(result.above,1);
  assert.equal(result.median,1);
  assert.equal(postSummary([post("only")]).median,null);
  assert.equal(result.buckets.reduce((sum,b)=>sum+b.count,0),4);
});

test("UTC week aggregation handles timezone offsets, missing weeks and invalid dates",()=>{
  const bins=weeklyPosts([post("a",{posted_at:"2026-10-11T23:30:00-05:00"}),post("b",{posted_at:"2026-10-12T01:00:00Z"}),post("c",{posted_at:"2026-10-26T09:00:00Z"}),post("invalid",{posted_at:"invalid"})]);
  assert.deepEqual(bins,[{date:"2026-10-12T00:00:00.000Z",posts:2},{date:"2026-10-19T00:00:00.000Z",posts:0},{date:"2026-10-26T00:00:00.000Z",posts:1}]);
  assert.deepEqual(weeklyPosts([]),[]);
});

test("unexpectedly wide date ranges stay bounded and preserve collected pieces",()=>{
  const bins=weeklyPosts([post("old",{posted_at:"2000-01-01T00:00:00Z"}),post("new",{posted_at:"2026-10-01T00:00:00Z"})]);
  assert.equal(bins.length,2);
  assert.equal(bins.reduce((sum,b)=>sum+b.posts,0),2);
});

test("topic filter keeps pending reviews but hides explicit exclusions",()=>{
  const items=[post("pending"),post("approved",{topic_review:{on_topic:true,subtopics:["ventas"]}}),post("excluded",{topic_review:{on_topic:false,subtopics:[]}})];
  assert.deepEqual(filterPosts(items,filters).map(p=>p.shortcode),["approved","pending"]);
  assert.equal(filterPosts(items,{...filters,onlyTopic:false}).length,3);
  assert.deepEqual(filterPosts(items,{...filters,search:"VENTAS"}).map(p=>p.shortcode),["approved"]);
});

test("filters intersect, known zero sorts before unknown, and the source is unchanged",()=>{
  const items=Object.freeze([post("unknown"),post("zero",{views:0}),post("top",{views:10,username:"otra.qa",label:"viral",content_type:"reel"})]);
  const original=items.map(p=>p.shortcode);
  assert.deepEqual(filterPosts(items,{...filters,sort:"views"}).map(p=>p.shortcode),["top","zero","unknown"]);
  assert.deepEqual(filterPosts(items,{...filters,creator:"otra.qa",label:"viral",format:"reel"}).map(p=>p.shortcode),["top"]);
  assert.equal(filterPosts(items,{...filters,creator:"otra.qa",format:"video"}).length,0);
  assert.deepEqual(items.map(p=>p.shortcode),original);
});
