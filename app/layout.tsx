import type {Metadata} from "next";
import "./globals.css";
import "./brand.css";
import "./motion.css";
import "./case-experience.css";
import "./auth-gate.css";
import CaseExperienceEnhancer from "./case-experience";
import AuthGate from "./auth-gate";

const configuredSiteUrl=process.env.NEXT_PUBLIC_SITE_URL;

export const metadata:Metadata={
 ...(configuredSiteUrl?{metadataBase:new URL(configuredSiteUrl)}:{}),
 title:"NEMESIS | Autonomous Crypto Incident Response",
 description:"Investigate crypto theft, trace every branch, monitor dormant funds, and prepare actionable evidence.",
 openGraph:{title:"NEMESIS",description:"Autonomous crypto incident response"},
 twitter:{card:"summary_large_image",title:"NEMESIS",description:"Autonomous crypto incident response"},
 icons:{icon:"/favicon.svg",shortcut:"/favicon.svg"}
};

export default function RootLayout({children}:{children:React.ReactNode}){
 return <html lang="en"><body><CaseExperienceEnhancer/><AuthGate/>{children}</body></html>
}
