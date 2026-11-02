// =============================================
// DATA — Enterprise Corporate Risk Register
// Standard Benchmark Dataset for AI+MCDM Engine
// =============================================

const companies = [
  { id: "BR-101", name: "Tata Motors",        sector: "Automotive",            risk: 78.4, level: "Critical", crisis: "EV Battery Safety Concerns",        sentiment: -0.82, reach: "High",   action: "Execute PR Response" },
  { id: "BR-102", name: "Infosys Ltd",         sector: "IT Services",           risk: 42.1, level: "Moderate", crisis: "Client Contract Delay Rumors",       sentiment: -0.35, reach: "Medium", action: "Monitor Feed" },
  { id: "BR-103", name: "Reliance Industries", sector: "Conglomerate",          risk: 24.5, level: "Low",      crisis: "Routine ESG Audit Scrutiny",         sentiment: -0.12, reach: "Low",    action: "Archive" },
  { id: "BR-104", name: "Zomato",              sector: "Consumer Tech",         risk: 82.9, level: "Critical", crisis: "Delivery Partner Wage Protest",       sentiment: -0.89, reach: "Viral",  action: "Immediate Legal Review" },
  { id: "BR-105", name: "ICICI Bank",          sector: "Banking & Finance",     risk: 61.3, level: "Moderate", crisis: "Regulatory Digital Lending Query",   sentiment: -0.54, reach: "Medium", action: "SEBI Alignment Check" },
  { id: "BR-106", name: "Adani Ports",         sector: "Infrastructure",        risk: 74.2, level: "Critical", crisis: "Environmental Clearance Delay",       sentiment: -0.76, reach: "High",   action: "Stakeholder Notification" },
  { id: "BR-107", name: "Hindustan Unilever",  sector: "FMCG",                  risk: 18.2, level: "Low",      crisis: "Minor Packaging Controversy",         sentiment: -0.05, reach: "Low",    action: "No Action Required" },
  { id: "BR-108", name: "Bharti Airtel",       sector: "Telecom",               risk: 39.8, level: "Moderate", crisis: "Metro Circle Network Outage",         sentiment: -0.44, reach: "High",   action: "Customer Support Route" },
  { id: "BR-109", name: "TCS",                 sector: "IT Services",           risk: 29.1, level: "Low",      crisis: "Executive Leadership Transition",     sentiment: -0.10, reach: "Low",    action: "Background Logging" },
  { id: "BR-110", name: "Paytm (One97)",       sector: "FinTech",               risk: 91.5, level: "Critical", crisis: "RBI Compliance Escalation",           sentiment: -0.95, reach: "Viral",  action: "Executive Crisis Protocol" },
  { id: "BR-111", name: "Sun Pharma",          sector: "Healthcare",            risk: 55.6, level: "Moderate", crisis: "USFDA Observation Notice",            sentiment: -0.58, reach: "Medium", action: "Legal Review Alert" },
  { id: "BR-112", name: "Larsen & Toubro",     sector: "Engineering",           risk: 22.4, level: "Low",      crisis: "Quarterly Margin Pressures",          sentiment: -0.08, reach: "Low",    action: "Archive" },
  { id: "BR-113", name: "ITC Limited",         sector: "FMCG",                  risk: 31.2, level: "Moderate", crisis: "Sin Tax Policy Speculation",          sentiment: -0.31, reach: "Medium", action: "Monitor Feed" },
  { id: "BR-114", name: "Tata Steel",          sector: "Metals & Mining",       risk: 68.7, level: "Moderate", crisis: "Carbon Emission Scrutiny",            sentiment: -0.62, reach: "High",   action: "Sustainability PR Draft" },
  { id: "BR-115", name: "Bajaj Finance",       sector: "NBFC",                  risk: 76.8, level: "Critical", crisis: "Unsecured Lending Portfolio Risk",     sentiment: -0.79, reach: "High",   action: "Investor Relations Alert" }
];

const sectors = [
  { name: "Banking & Financial Services", low: 12, moderate: 24, critical: 8,  avg: 58.4 },
  { name: "Consumer Tech & E-Commerce",   low: 5,  moderate: 9,  critical: 14, avg: 72.1 },
  { name: "IT & Technology Services",     low: 28, moderate: 15, critical: 3,  avg: 36.2 },
  { name: "Automotive & Manufacturing",   low: 8,  moderate: 14, critical: 7,  avg: 54.9 },
  { name: "Energy & Infrastructure",      low: 14, moderate: 11, critical: 5,  avg: 48.3 }
];
