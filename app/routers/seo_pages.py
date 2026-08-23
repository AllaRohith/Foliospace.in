"""SEO landing pages — one per role/vertical.

Each page renders app/templates/seo/_base.html with content tailored to the
search intent (e.g. "developer portfolio India", "chef portfolio"). Pages
return honest, factual copy and link back to /signup and /pricing — no
fabricated testimonials, no fake counts.

Routes are mounted from app/main.py after the static pages so they don't
shadow /<slug> for real users.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


def _ctx(page_key: str, crumb: str, eyebrow: str, title: str, lede: str,
 why_points, features, steps, honest, faqs, description: str):
 return {
 "page_key": page_key,
 "crumb": crumb,
 "eyebrow": eyebrow,
 "title": title,
 "lede": lede,
 "why_points": why_points,
 "features": features,
 "steps": steps,
 "honest": honest,
 "faqs": faqs,
 "description": description,
 }


def _render(request: Request, template: str, page_key: str, **kwargs) -> HTMLResponse:
 from app.main import templates
 from app.pricing import (
 PRO_YEAR1_INR, PRO_YEAR2_INR, FOUNDER_COHORT_LIMIT,
 fmt_inr, trial_label,
 )
 ctx = {
 "page_key": page_key,
 "site_name": "FolioSpace",
 "FREE_PRICE_INR": 0,
 "PRO_YEAR1_INR": PRO_YEAR1_INR,
 "PRO_YEAR2_INR": PRO_YEAR2_INR,
 "FOUNDER_COHORT_LIMIT": FOUNDER_COHORT_LIMIT,
 "fmt_inr": fmt_inr,
 "trial_label": trial_label,
 }
 ctx.update(kwargs)
 return templates.TemplateResponse(request, template, ctx)


# ---------- portfolio-builder (generic) ----------

@router.get("/portfolio-builder")
async def portfolio_builder(request: Request):
 return _render(
 request,
 "seo/_base.html",
 page_key="portfolio-builder",
 crumb="Portfolio builder",
 eyebrow="For every Indian professional",
 title="A portfolio builder that fits how India actually works.",
 lede="FolioSpace gives you a fast public folio at your own slug, with WhatsApp-ready share, UPI AutoPay billing, and the basics done right. No design skills required.",
 why_points=[
 {"title": "Your own slug, not a subdomain.",
 "body": "You get foliospace.in/<your-name>, indexed by Google, shareable as one clean link. No foliospace.in/users/xj4q to copy-paste."},
 {"title": "Built for WhatsApp, not just desktop.",
 "body": "Open-graph previews are sized for phone screens. Your WhatsApp contact card stops being a grey link and starts showing your work."},
 {"title": "UPI-native billing.",
 "body": "Pro is ₹899/yr in Year 1 (launch offer, 40% off) and ₹1,499/yr from Year 2, billed via Cashfree UPI AutoPay or Card AutoPay. No card, no foreign currency, no surprises. Free forever for the basics."},
 {"title": "Honest about what's done.",
 "body": "We say exactly which integrations are live, which are coming, and which we deliberately won't build. See the features page."},
 ],
 features=[
 {"title": "Profile + bio + portfolio links", "body": "Editable from a single form. Works on phone or laptop."},
 {"title": "Custom links", "body": "Up to 10 on Free, unlimited on Pro. Stack, grid, or carousel layout."},
 {"title": "Spotlight card", "body": "Pin one project, repo, or thought to the top of your folio."},
 {"title": "Visit counter", "body": "Per-day visitor sparkline on your dashboard. No third-party tracking."},
 {"title": "QR code", "body": "A printable QR for printed cards, resumes, and shop counters."},
 {"title": "Avatar upload", "body": "Direct to image CDN with a built-in cropper. Stored, not proxied."},
 ],
 steps=[
 {"title": "Claim your slug", "body": "Pick your handle. If it's taken, the form tells you immediately."},
 {"title": "Fill the basics", "body": "Name, role, bio, links. Takes about three minutes."},
 {"title": "Publish", "body": "Flip the public switch. Your folio is live at foliospace.in/<slug>."},
 {"title": "Share", "body": "Copy, WhatsApp, QR, LinkedIn — one tap each. Visit counter starts filling in."},
 ],
 honest=[
 "FolioSpace is a portfolio builder, not a website builder. No pages, no blog, no commerce.",
 "Free plan keeps your folio at foliospace.in/<slug>. Custom domains are on the roadmap.",
 "We don't sell or share your data. Period. See the privacy page for the long version.",
 "Free folios are public. You can unpublish any time, but you can't make a single folio visible only to specific people — that's a paid feature we're still designing.",
 ],
 faqs=[
 {"q": "Do I need to know HTML or CSS?",
 "a": "No. You fill a form; the folio renders from your data. Designers and developers can still drop in custom CSS via Pro later."},
 {"q": "Can I use my own domain?",
 "a": "Not yet. Custom domains are on the roadmap. Until then, you get a clean foliospace.in/<slug> URL."},
 {"q": "Is there a free plan?",
 "a": "Yes. Free folios include the basics — profile, bio, up to 10 links, and QR. Pro adds unlimited links, analytics, custom CSS, and removes the small 'Made with FolioSpace' footer."},
 {"q": "How do I get paid if I want Pro?",
 "a": "UPI AutoPay via Cashfree. You authorise a small annual debit (₹899 in Year 1, ₹1,499 from Year 2) and cancel any time from your dashboard or your bank's app."},
 ],
 description="FolioSpace is a portfolio builder for Indian professionals. Get a fast public folio at your own slug, with WhatsApp-ready previews and UPI AutoPay billing.",
 )


# ---------- student-portfolio ----------

@router.get("/student-portfolio")
async def student_portfolio(request: Request):
 return _render(
 request,
 "seo/_base.html",
 page_key="student-portfolio",
 crumb="Student portfolio",
 eyebrow="For college students and fresh grads",
 title="A student portfolio that actually gets you interviews.",
 lede="FolioSpace gives you a clean folio you can drop into placement forms, WhatsApp introductions, and cold emails — without spending a weekend wrestling with a website builder.",
 why_points=[
 {"title": "Done in a single sitting.",
 "body": "Most students finish in under fifteen minutes. The form has six fields and a save button."},
 {"title": "Looks serious on placements.",
 "body": "A real link at foliospace.in/<name> reads better than a Notion page or a Google Doc. Recruiters click it."},
 {"title": "Free forever for what you need.",
 "body": "The Free plan covers everything a placement season needs. Pro is for after you land the role."},
 ],
 features=[
 {"title": "Resume link", "body": "Pin your resume PDF at the top of every folio."},
 {"title": "Project cards", "body": "Add GitHub repos and a one-liner about each."},
 {"title": "LinkedIn import", "body": "Pull your headline and bio so you don't type them twice."},
 {"title": "Printable QR", "body": "Drop into your placement form or print on a batch of business cards."},
 {"title": "Mobile-ready", "body": "Recruiters open these on phones. Yours will look right."},
 {"title": "Public or unlisted", "body": "Free folios are public — you can unpublish any time from your dashboard."},
 ],
 steps=[
 {"title": "Sign up with your college email", "body": "GitHub or LinkedIn sign-in also works if you have either."},
 {"title": "Pick a slug", "body": "Your name, or your-name-dev, or your-handle — whatever recruiters will recognise."},
 {"title": "Add three projects", "body": "GitHub repos or static links. One line about each is plenty."},
 {"title": "Publish and share", "body": "Drop the link into placement forms, WhatsApp intros, and LinkedIn DMs."},
 ],
 honest=[
 "FolioSpace is not a placement guarantee. It's a clean link you control.",
 "Free folios are public to anyone with the link. Unpublish when you're done with placements.",
 "We don't show ads. Your data isn't sold.",
 ],
 faqs=[
 {"q": "Is FolioSpace free for students?",
 "a": "Yes. The Free plan is free for everyone, including students. Pro is optional and only needed for features Free doesn't cover."},
 {"q": "Can I link my college work?",
 "a": "Yes — drop PDFs, GitHub repos, Figma files, or any link. Free plan covers up to 10 links."},
 {"q": "Will my folio show up on Google?",
 "a": "Folios are indexed by default. You can request noindex from your dashboard if you'd rather not be searchable."},
 {"q": "What about after I graduate?",
 "a": "Your folio stays yours. Upgrade to Pro any time to add custom CSS, unlimited links, and analytics."},
 ],
 description="A clean student portfolio at your own URL. Free for college students and fresh grads. Pin your projects, resume, and links in one place.",
 )


# ---------- developer-portfolio ----------

@router.get("/developer-portfolio")
async def developer_portfolio(request: Request):
 return _render(
 request,
 "seo/_base.html",
 page_key="developer-portfolio",
 crumb="Developer portfolio",
 eyebrow="For engineers and builders",
 title="A developer portfolio that shows your work, not your CMS.",
 lede="FolioSpace is for engineers who'd rather ship than theme. Drop your repos, pin a Spotlight card, link your GitHub — done.",
 why_points=[
 {"title": "GitHub import.",
 "body": "Pull public repos and a 53-week contribution grid straight from your GitHub profile."},
 {"title": "Spotlight your best work.",
 "body": "Pin one repo or project to the top of your folio with a card-style hero."},
 {"title": "Fast.",
 "body": "Server-rendered, no JS framework in the browser, no client-side hydration. Lighthouse-friendly by default."},
 ],
 features=[
 {"title": "GitHub repo cards", "body": "Auto-imported. Star count, language, and a one-line description per repo."},
 {"title": "Contribution grid", "body": "53-week commit heatmap, rendered server-side."},
 {"title": "LinkedIn basic profile", "body": "Headline and bio imported. Use it as a starting point."},
 {"title": "Custom links", "body": "Stack, grid, or carousel. Up to 10 on Free, unlimited on Pro."},
 {"title": "Custom CSS (Pro)", "body": "A small CSS editor for the parts of the folio you'd like to restyle."},
 {"title": "Open Graph image", "body": "Auto-generated PNG per folio. Looks right on LinkedIn, Slack, and WhatsApp."},
 ],
 steps=[
 {"title": "Sign up with GitHub", "body": "OAuth — no password to remember. We pull your profile picture and bio."},
 {"title": "Run the importer", "body": "One click on /manage. Pulls repos and contribution grid."},
 {"title": "Edit the Spotlight card", "body": "Pin the repo you want recruiters to open first."},
 {"title": "Publish", "body": "Your folio is live. Share the link in cold emails and applications."},
 ],
 honest=[
 "FolioSpace is not a CMS. You can't add arbitrary pages, only a fixed folio layout.",
 "The contribution grid is from GitHub's public API. Private work doesn't count.",
 "Custom CSS is Pro. Free folios look the way they look — which is fine for most engineers.",
 ],
 faqs=[
 {"q": "Is there a static-site-generator option?",
 "a": "Not yet. The folio is rendered server-side. We're tracking a static-export option in the roadmap."},
 {"q": "Can I import private repos?",
 "a": "No. We only pull public repos via the GitHub API. Use a private GitHub Pages site if you need private work shown."},
 {"q": "Does the folio support code highlighting?",
 "a": "Yes, via a Spotlight card that supports fenced code blocks. The full portfolio page is intentionally simple — it links out to your repos."},
 {"q": "How do I delete my folio?",
 "a": "From your dashboard. Deletion is permanent and removes all data we hold about you."},
 ],
 description="A developer portfolio for engineers who'd rather ship than theme. GitHub repo import, contribution grid, and a clean customisable layout.",
 )


# ---------- designer-portfolio ----------

@router.get("/designer-portfolio")
async def designer_portfolio(request: Request):
 return _render(
 request,
 "seo/_base.html",
 page_key="designer-portfolio",
 crumb="Designer portfolio",
 eyebrow="For product, graphic, and UI designers",
 title="A designer portfolio that lets the work speak.",
 lede="FolioSpace keeps the chrome quiet so your case studies and prototypes carry the page. Edit once, share everywhere.",
 why_points=[
 {"title": "Spotlight card for the work you want seen.",
 "body": "Pin one project to the top — Figma embed, Behance link, or a one-line write-up with a hero image."},
 {"title": "Custom CSS, when you need it.",
 "body": "Pro unlocks a small CSS editor for the parts of the folio you'd like to restyle."},
 {"title": "Quiet typography.",
 "body": "Two type families, generous line height, and minimal chrome. The work is the hero."},
 ],
 features=[
 {"title": "Avatar upload", "body": "Direct to image CDN with a built-in cropper."},
 {"title": "Custom links", "body": "Stack, grid, or carousel layout. Up to 10 on Free, unlimited on Pro."},
 {"title": "Open Graph image", "body": "Per-folio PNG, generated server-side. Looks right on Dribbble, LinkedIn, and Slack."},
 {"title": "Mobile-responsive", "body": "Tested at 320, 360, 390, 414, 768, and 1440. Looks right on phones."},
 {"title": "QR code", "body": "Drop into a Behance post or print on the back of a business card."},
 {"title": "LinkedIn import", "body": "Pull your headline and bio to save typing."},
 ],
 steps=[
 {"title": "Sign up", "body": "Email, GitHub, or LinkedIn."},
 {"title": "Upload your work", "body": "Add links to Figma, Behance, Dribbble, or your own site."},
 {"title": "Pin a Spotlight", "body": "Pick the one project you want recruiters to open first."},
 {"title": "Publish", "body": "Share the link in applications and on your existing profiles."},
 ],
 honest=[
 "FolioSpace is not a Behance replacement. It's a link you control, optimised for sharing.",
 "Free folios carry a small 'Made with FolioSpace' line in the footer. Pro removes it.",
 "We're a small product. Custom requests go to the roadmap, not to a ticket queue.",
 ],
 faqs=[
 {"q": "Can I embed Figma or Framer prototypes?",
 "a": "Yes — use the Custom links section. Drop the Figma share URL and we render it as a card."},
 {"q": "Can I upload high-res images?",
 "a": "No — FolioSpace is a profile, not a gallery. Link out to Behance or your own image host for full-res work."},
 {"q": "Is there a portfolio template gallery?",
 "a": "There's one template today. More are on the roadmap as the product stabilises."},
 {"q": "How do I switch templates?",
 "a": "From your dashboard at /<slug>/manage/templates. All templates are currently in 'Coming soon' state while we stabilise the default."},
 ],
 description="A designer portfolio for product, graphic, and UI designers. Pin your best work, share one clean link, and let the case studies carry the page.",
 )


# ---------- chef-portfolio ----------

@router.get("/chef-portfolio")
async def chef_portfolio(request: Request):
 return _render(
 request,
 "seo/_base.html",
 page_key="chef-portfolio",
 crumb="Chef portfolio",
 eyebrow="For chefs, bakers, and home cooks",
 title="A chef portfolio that looks right on a phone.",
 lede="FolioSpace is for chefs who want a clean link to send to a supplier, a customer, or a hiring manager — without learning a website builder.",
 why_points=[
 {"title": "WhatsApp-first.",
 "body": "Your folio previews correctly on WhatsApp, the way your customers and suppliers actually share it."},
 {"title": "Printable QR.",
 "body": "A QR code is generated for every folio. Drop it on a counter, a menu, or a takeaway box."},
 {"title": "Editable anytime.",
 "body": "You can edit your folio from your phone. Same link, same slug."},
 ],
 features=[
 {"title": "Profile + bio", "body": "Name, specialty, where you cook. Plus a one-line about-you."},
 {"title": "Custom links", "body": "Menu, Zomato/Swiggy, Instagram, or your own order page. Up to 10 on Free."},
 {"title": "Open Graph image", "body": "Looks right when shared on Instagram DMs and WhatsApp groups."},
 {"title": "Public/unlisted toggle", "body": "Unpublish when you're between gigs. Republish with one click."},
 {"title": "Avatar upload", "body": "Direct to image CDN. Stored, not proxied."},
 ],
 steps=[
 {"title": "Sign up", "body": "Email or Google. About two minutes."},
 {"title": "Add your links", "body": "Menu, Instagram, Swiggy, or your own order page."},
 {"title": "Generate a QR", "body": "Print it, drop it on a counter or takeaway box."},
 {"title": "Share", "body": "Send the link on WhatsApp. Previews look right."},
 ],
 honest=[
 "FolioSpace is not a full website. It's a single clean link you control.",
 "We don't list your address publicly. Add a Google Maps link only if you want to.",
 "Free folios are public. Unpublish any time from your dashboard.",
 ],
 faqs=[
 {"q": "Can customers order through my folio?",
 "a": "Not directly. FolioSpace is a profile, not a commerce platform. Link out to your existing order page (Swiggy, Zomato, your own site)."},
 {"q": "Can I show today's specials?",
 "a": "Use the Spotlight card. It's a one-line card at the top of your folio — swap it daily if you like."},
 {"q": "Will the QR code work on a printed menu?",
 "a": "Yes. The QR encodes the folio URL. Print at any size and it scans the same way."},
 ],
 description="A chef portfolio for chefs, bakers, and home cooks. WhatsApp-ready previews, printable QR, and a clean link to send suppliers and customers.",
 )


# ---------- consultant-portfolio ----------

@router.get("/consultant-portfolio")
async def consultant_portfolio(request: Request):
 return _render(
 request,
 "seo/_base.html",
 page_key="consultant-portfolio",
 crumb="Consultant portfolio",
 eyebrow="For independent consultants",
 title="A consultant portfolio that closes more intros.",
 lede="FolioSpace is for consultants who'd rather send one link than a deck. Bio, expertise, case-study links, and a Calendly — all in one URL.",
 why_points=[
 {"title": "Looks right on cold email.",
 "body": "Your folio previews correctly on Gmail, Outlook, and LinkedIn DMs. Recipients don't see a grey link."},
 {"title": "Custom links, no clutter.",
 "body": "Calendly, Substack, your latest report — pin them to the top in a stack or grid."},
 {"title": "Subtle, professional design.",
 "body": "Quiet typography, no animations, no splash pages. The bio and the work are the page."},
 ],
 features=[
 {"title": "Profile + bio", "body": "Headline, specialty, focus areas. Up to 280 characters."},
 {"title": "Custom links", "body": "Calendly, Substack, your own site. Up to 10 on Free."},
 {"title": "LinkedIn import", "body": "Pull your headline and bio to save typing."},
 {"title": "Open Graph image", "body": "Server-rendered PNG per folio. Looks right on LinkedIn and Slack."},
 {"title": "Visit counter", "body": "See which intros actually opened your link. Pro only."},
 ],
 steps=[
 {"title": "Sign up", "body": "Email or LinkedIn."},
 {"title": "Add your Calendly and Substack", "body": "Custom links, stack layout, one above the other."},
 {"title": "Pin a Spotlight", "body": "Your latest report, talk, or case study."},
 {"title": "Drop the link into your email signature", "body": "Replaces the long LinkedIn URL."},
 ],
 honest=[
 "FolioSpace is not a CRM. It doesn't track opens, doesn't send mail, doesn't auto-follow-up.",
 "We don't replace LinkedIn. We make the link in your LinkedIn bio worth clicking.",
 "Free folios are public. Unpublish when you're between engagements.",
 ],
 faqs=[
 {"q": "Can I track who visits my folio?",
 "a": "Pro shows daily visit counts. We don't show identity, IP, or referrer of individual visitors."},
 {"q": "Can I gate the folio behind a password?",
 "a": "Not yet. Free folios are public. We're designing a private-share feature for Pro."},
 {"q": "Will my Calendly link be tracked?",
 "a": "No — we don't inject tracking pixels or scripts into your links."},
 ],
 description="A consultant portfolio for independent consultants. Send one clean link instead of a deck. Calendly, Substack, and case-study links in one URL.",
 )


# ---------- freelancer-portfolio ----------

@router.get("/freelancer-portfolio")
async def freelancer_portfolio(request: Request):
 return _render(
 request,
 "seo/_base.html",
 page_key="freelancer-portfolio",
 crumb="Freelancer portfolio",
 eyebrow="For freelancers and contractors",
 title="A freelancer portfolio that ships with the work, not before it.",
 lede="FolioSpace is for freelancers who want a real link in their proposals without spending a weekend on a website. Bio, work, links — done.",
 why_points=[
 {"title": "Done in fifteen minutes.",
 "body": "Most freelancers finish the basics in a single sitting. The form has six fields."},
 {"title": "Custom links for your tools.",
 "body": "Calendly, Notion portfolio, Fiverr, Upwork — pin them in the order clients should see them."},
 {"title": "Pro for proposals.",
 "body": "Add visit analytics to learn which proposals actually opened your folio. Pro only."},
 ],
 features=[
 {"title": "Profile + bio", "body": "Name, specialty, what you take on."},
 {"title": "Custom links", "body": "Stack, grid, or carousel layout. Up to 10 on Free."},
 {"title": "Open Graph image", "body": "Looks right on Twitter DMs, Slack, and Gmail."},
 {"title": "Spotlight card", "body": "Pin one project or testimonial link to the top."},
 {"title": "Visit counter (Pro)", "body": "Per-day visitor sparkline. No third-party tracking."},
 ],
 steps=[
 {"title": "Sign up", "body": "Email, GitHub, or LinkedIn."},
 {"title": "Add your tool links", "body": "Calendly, Notion, Fiverr, Upwork — whatever clients need."},
 {"title": "Pin a Spotlight", "body": "The project or case study you want leads to open first."},
 {"title": "Drop the link into proposals", "body": "Replaces a generic LinkedIn URL."},
 ],
 honest=[
 "FolioSpace is not an invoicing or contract tool. Use your existing stack for that.",
 "Free folios are public. Unpublish any time from your dashboard.",
 "We don't show ads. We don't sell data. We don't auto-DM leads on your behalf.",
 ],
 faqs=[
 {"q": "Can I add testimonials?",
 "a": "Use the Spotlight card to link to a Notion, Google Doc, or LinkedIn post with your testimonial. We don't render testimonials inline yet."},
 {"q": "Can I track who opens my folio?",
 "a": "Pro shows per-day counts. We don't track individual visitors."},
 {"q": "What if my slug is taken?",
 "a": "The signup form tells you immediately and suggests alternates."},
 ],
 description="A freelancer portfolio for freelancers and contractors. Bio, custom links, and a Spotlight card — done in fifteen minutes.",
 )


# ---------- small-business-website ----------

@router.get("/small-business-website")
async def small_business_website(request: Request):
 return _render(
 request,
 "seo/_base.html",
 page_key="small-business-website",
 crumb="Small-business website",
 eyebrow="For shops, studios, and local services",
 title="A small-business website that doesn't need a developer.",
 lede="FolioSpace is a one-page online presence for shops, studios, and local services. One link, one QR, one place to point customers.",
 why_points=[
 {"title": "One link, not a CMS.",
 "body": "FolioSpace is a single page. You don't need to learn a website builder. You fill a form."},
 {"title": "QR for printed material.",
 "body": "Print the QR on a window, a counter card, or a takeaway box. Customers scan and reach your folio."},
 {"title": "WhatsApp-ready.",
 "body": "Your folio previews correctly when shared on WhatsApp — which is where most local business intros happen."},
 ],
 features=[
 {"title": "Profile + bio", "body": "What you do, where you are, hours."},
 {"title": "Custom links", "body": "Map, Swiggy, Zomato, Justdial, your own booking page. Up to 10 on Free."},
 {"title": "Open Graph image", "body": "Looks right when shared on WhatsApp, Instagram DMs, and Google reviews."},
 {"title": "Spotlight card", "body": "Pin today's special, an offer, or a featured service."},
 {"title": "Public/unlisted toggle", "body": "Unpublish during renovations. Republish with one click."},
 ],
 steps=[
 {"title": "Sign up", "body": "Email or Google. About two minutes."},
 {"title": "Add your map and ordering links", "body": "Google Maps, Swiggy, Zomato, Justdial, or your own booking page."},
 {"title": "Print the QR", "body": "Stick it on the door or the takeaway box."},
 {"title": "Share on WhatsApp", "body": "Customers forward the link. Previews look right."},
 ],
 honest=[
 "FolioSpace is a profile, not a website builder. No multi-page navigation, no blog, no commerce.",
 "Free folios are public. Unpublish any time from your dashboard.",
 "We don't process orders or take payments. FolioSpace is the link, not the checkout.",
 ],
 faqs=[
 {"q": "Can customers order through my folio?",
 "a": "Not directly. FolioSpace is a profile, not a checkout. Link out to Swiggy, Zomato, or your own order page."},
 {"q": "Can I show my address on the folio?",
 "a": "Use the Custom links section to pin a Google Maps link. We don't display your address inline by default."},
 {"q": "What if I want a multi-page site?",
 "a": "FolioSpace isn't built for that. Use a website builder. We're a one-page link with a clean design."},
 ],
 description="A small-business website for shops, studios, and local services. One link, one QR, one place to point customers — no developer needed.",
 )


def list_seo_paths() -> list[tuple[str, str]]:
 """Return [(path, lastmod)] for sitemap.xml entries.

 lastmod is intentionally left empty so the sitemap picks up today's date.
 """
 return [
 ("/portfolio-builder", ""),
 ("/student-portfolio", ""),
 ("/developer-portfolio", ""),
 ("/designer-portfolio", ""),
 ("/chef-portfolio", ""),
 ("/consultant-portfolio", ""),
 ("/freelancer-portfolio", ""),
 ("/small-business-website", ""),
 ]