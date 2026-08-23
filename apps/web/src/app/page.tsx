import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Veritech Site Checker — Technical Pre-Screening for Web-Based Business Acquisitions",
};

export default function HomePage() {
  return (
    <div className="landing">
      <style>{`
        .landing {
          --ink: #0A0A0A;
          --paper: #FAFAF7;
          --muted: #5B5B5B;
          --rule: #E5E5E0;
          --accent: #1F3A5F;
          --accent-hover: #132845;
          --parchment: #EFEBE0;

          background: var(--paper);
          color: var(--ink);
          font-family: var(--font-sans), -apple-system, sans-serif;
          line-height: 1.65;
        }

        .landing .mono {
          font-family: var(--font-mono), monospace;
        }

        .landing .eyebrow {
          font-family: var(--font-mono), monospace;
          font-size: 0.6875rem;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--muted);
          margin: 0 0 1rem 0;
        }

        .landing a { color: var(--accent); }

        .landing a:focus-visible,
        .landing button:focus-visible {
          outline: 2px solid var(--accent);
          outline-offset: 3px;
        }

        .landing .outer {
          max-width: 960px;
          margin: 0 auto;
          padding: 0 24px;
        }

        @media (min-width: 1024px) {
          .landing .outer { padding: 0 48px; }
        }

        /* ---------- Site header ---------- */

        .landing .site-header {
          border-bottom: 1px solid var(--rule);
        }

        .landing .site-header-inner {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 24px;
          padding: 20px 0;
        }

        .landing .brand {
          font-family: var(--font-mono), monospace;
          font-size: 0.6875rem;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--ink);
          text-decoration: none;
        }

        .landing .btn-header {
          display: inline-flex;
          align-items: center;
          background: var(--accent);
          color: var(--paper);
          text-decoration: none;
          padding: 10px 20px;
          font-size: 14px;
          font-weight: 500;
          border: none;
          transition: background 0.15s ease;
          white-space: nowrap;
        }

        .landing .btn-header:hover { background: var(--accent-hover); }

        /* ---------- Hero ---------- */

        .landing .hero {
          padding: 96px 0 56px 0;
          border-bottom: 1px solid var(--rule);
        }

        .landing .hero-inner {
          max-width: 680px;
        }

        .landing .hero h1 {
          font-size: 2.25rem;
          line-height: 1.05;
          font-weight: 800;
          letter-spacing: -0.025em;
          margin: 0 0 32px 0;
        }

        @media (min-width: 768px) {
          .landing .hero h1 { font-size: 3rem; }
        }

        @media (min-width: 1024px) {
          .landing .hero h1 { font-size: 3.25rem; line-height: 1; }
        }

        .landing .hero .standfirst {
          font-size: 1.125rem;
          font-variation-settings: normal;
          font-weight: 400;
          line-height: 1.625;
          color: var(--ink);
          margin: 0 0 32px 0;
          max-width: 680px;
        }

        @media (min-width: 768px) {
          .landing .hero .standfirst { font-size: 1.25rem; }
        }

        .landing .cta-row {
          display: flex;
          align-items: center;
          gap: 32px;
          flex-wrap: wrap;
        }

        .landing .btn-primary {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          background: var(--accent);
          color: var(--paper);
          text-decoration: none;
          padding: 14px 24px;
          font-size: 15px;
          font-weight: 500;
          border: none;
          border-radius: 0;
          cursor: pointer;
          transition: background 0.15s ease;
        }

        .landing .btn-primary:hover { background: var(--accent-hover); }

        .landing .btn-primary .arrow { transition: transform 0.15s ease; display: inline-block; }
        .landing .btn-primary:hover .arrow { transform: translateX(3px); }

        .landing .btn-secondary {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          color: var(--ink);
          text-decoration: none;
          border-bottom: 1px solid var(--ink);
          padding: 14px 0;
          font-size: 15px;
          font-weight: 500;
          transition: gap 0.15s ease;
        }

        .landing .btn-secondary:hover { gap: 12px; }

        .landing .btn-secondary .arrow { transition: transform 0.15s ease; display: inline-block; }
        .landing .btn-secondary:hover .arrow { transform: translateX(2px); }

        @media (prefers-reduced-motion: reduce) {
          .landing .btn-primary, .landing .btn-secondary, .landing .arrow { transition: none; }
        }

        /* ---------- Sections ---------- */

        .landing .section {
          padding: 56px 0;
          border-bottom: 1px solid var(--rule);
        }

        .landing .section-grid {
          display: grid;
          grid-template-columns: 56px 1fr;
          gap: 0 24px;
        }

        .landing .section-num {
          font-family: var(--font-mono), monospace;
          font-size: 0.75rem;
          color: var(--muted);
          padding-top: 6px;
        }

        .landing .section-content {
          max-width: 680px;
        }

        .landing h2 {
          font-size: 2.25rem;
          font-weight: 700;
          letter-spacing: -0.01em;
          margin: 0 0 20px 0;
          line-height: 1.25em;
        }

        .landing .copy {
          font-size: 1.0625rem;
          line-height: 1.7;
          margin: 0 0 16px 0;
        }

        .landing .copy:last-child { margin-bottom: 0; }

        /* ---------- Check table ---------- */

        .landing .check-table {
          width: 100%;
          border-collapse: collapse;
          margin-top: 8px;
        }

        .landing .check-table th {
          text-align: left;
          font-family: var(--font-mono), monospace;
          font-size: 0.6875rem;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          color: var(--muted);
          font-weight: 500;
          padding: 0 0 12px 0;
          border-bottom: 1px solid var(--ink);
        }

        .landing .check-table td {
          padding: 16px 0;
          border-bottom: 1px solid var(--rule);
          font-size: 1rem;
          line-height: 1.55;
          vertical-align: top;
        }

        .landing .check-table tr:last-child td { border-bottom: 1px solid var(--ink); }

        .landing .check-table td.cat {
          font-weight: 600;
          width: 38%;
          padding-right: 24px;
        }

        .landing .check-table td.desc { color: var(--muted); }

        /* ---------- Access section ---------- */

        .landing .access {
          padding: 64px 0 96px 0;
        }

        .landing .access-inner {
          max-width: 680px;
        }

        .landing .access-copy {
          font-size: 1.0625rem;
          color: var(--muted);
          margin: 0 0 32px 0;
          max-width: 560px;
        }

        /* ---------- Footer ---------- */

        .landing footer {
          padding: 32px 0;
        }

        .landing footer p {
          font-family: var(--font-mono), monospace;
          font-size: 0.6875rem;
          letter-spacing: 0.06em;
          color: var(--muted);
          margin: 0;
        }

        /* ---------- Mobile ---------- */

        @media (max-width: 640px) {
          .landing .hero { padding: 56px 0 40px 0; }
          .landing .section { padding: 40px 0; }
          .landing .section-grid { grid-template-columns: 1fr; }
          .landing .section-num { padding-top: 0; margin-bottom: 12px; }
          .landing h2 { font-size: 1.6rem; }
          .landing .check-table td.cat { width: 44%; }
          .landing .cta-row { gap: 20px; }
        }
      `}</style>

      <header className="site-header">
        <div className="outer site-header-inner">
          <Link href="/" className="brand">
            Veritech Diligence
          </Link>
          <Link href="/login" className="btn-header">
            Scan a site
          </Link>
        </div>
      </header>

      <section className="hero">
        <div className="outer">
          <div className="hero-inner">
            <p className="eyebrow">Veritech Site Checker — an automated tool from Veritech Diligence</p>
            <h1>Run an analysis on the site you&rsquo;re about to buy. See exactly what you need to know.</h1>
            <p className="standfirst">
              Enter the domain you&rsquo;re evaluating. Scan automatically checks what&rsquo;s already public, DNS
              posture, redirects, third-party dependencies, and the technology behind the site, and returns a risk
              register in minutes. No analyst sits between you and the result, and every finding links back to the
              exact evidence behind it.
            </p>

            <div className="cta-row">
              <Link href="/login" className="btn-primary">
                Start a free scan <span className="arrow">→</span>
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="outer">
          <div className="section-grid">
            <div className="section-num">01</div>
            <div className="section-content">
              <p className="eyebrow">The question it answers</p>
              <h2>Is this worth a full technical review?</h2>
              <p className="copy">
                You&rsquo;re looking at a listing on Acquire.com, Flippa, or through a broker, and you need to know
                quickly whether it holds up before you spend real time or ask a seller for system access. Scan
                reads what&rsquo;s already public: the DNS records, the response headers, the homepage as
                rendered, the dependencies it loads.
              </p>
              <p className="copy">
                It runs the moment you submit a domain, no scheduling and no waiting on an analyst, and returns a
                prioritized answer in minutes rather than days: what&rsquo;s solid, what needs a closer look, and
                what should stop you before you go further.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="outer">
          <div className="section-grid">
            <div className="section-num">02</div>
            <div className="section-content">
              <p className="eyebrow">What it checks</p>
              <h2>Six categories, one evidence trail.</h2>
              <table className="check-table">
                <thead>
                  <tr>
                    <th>Category</th>
                    <th>What it tells you</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="cat">Site behavior and redirects</td>
                    <td className="desc">
                      How the live site actually responds, and whether redirect chains or broken paths are hiding
                      problems.
                    </td>
                  </tr>
                  <tr>
                    <td className="cat">Email and domain posture</td>
                    <td className="desc">
                      Whether SPF and DMARC are configured to stop spoofing, and what that says about how the
                      domain has been maintained.
                    </td>
                  </tr>
                  <tr>
                    <td className="cat">Crawl and structure</td>
                    <td className="desc">
                      A bounded, same-origin read of how the site is organized, checked against what robots.txt and
                      the sitemap claim.
                    </td>
                  </tr>
                  <tr>
                    <td className="cat">Technology stack</td>
                    <td className="desc">
                      What&rsquo;s actually running the site — CMS and website-builder platforms, e-commerce,
                      frontend frameworks, analytics and tag managers, advertising and email marketing, customer
                      support and chat, payments, CDN and hosting, fonts and JS libraries, consent management,
                      forms and scheduling, search, captcha, and embedded video or maps — detected from the
                      public-facing code, not guessed.
                    </td>
                  </tr>
                  <tr>
                    <td className="cat">Third-party dependencies</td>
                    <td className="desc">
                      What the homepage loads from outside services, and what that means for risk and vendor
                      lock-in after close.
                    </td>
                  </tr>
                  <tr>
                    <td className="cat">Performance</td>
                    <td className="desc">Core Web Vitals and load behavior, the same signals search engines use to judge the site.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="outer">
          <div className="section-grid">
            <div className="section-num">03</div>
            <div className="section-content">
              <p className="eyebrow">How a finding becomes a finding</p>
              <h2>Every finding traces back to evidence.</h2>
              <p className="copy">
                A fixed set of twelve rules, not a person and not a model guessing, turns what Scan collects into
                severity- and confidence-scored findings automatically. Click into any finding in the risk register
                and see the exact HTTP response, DNS record, or rendered page behind it.
              </p>
              <p className="copy">The system separates what it observed from what that observation might mean. A hardening opportunity is never presented as a confirmed vulnerability.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="outer">
          <div className="section-grid">
            <div className="section-num">04</div>
            <div className="section-content">
              <p className="eyebrow">What Scan does not do</p>
              <h2>A boundary, stated plainly.</h2>
              <p className="copy">
                Scan is fully automated and stays inside a fixed boundary. It only reads what&rsquo;s already
                public, and it does not attempt to log in, test credentials, bypass access controls, or confirm a
                vulnerability by exploiting it. Where it flags something that could be a security gap, the report
                labels it as an observation, not a confirmed compromise.
              </p>
              <p className="copy">Scan gives you a first read. It does not replace the full nine-layer technical review once a target is worth pursuing further.</p>
              <a href="https://veritechdiligence.com/#contact" className="btn-secondary">
                See what the full review covers <span className="arrow">→</span>
              </a>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="outer">
          <div className="section-grid">
            <div className="section-num">05</div>
            <div className="section-content">
              <p className="eyebrow">Why it matters inside your window</p>
              <h2>Where to focus, not just whether to look further.</h2>
              <p className="copy">
                You&rsquo;re working inside a limited evaluation window, and most of what you need to decide
                whether to go deeper is already sitting in public records and the page itself. Scan runs the moment
                you enter a domain, before you ask a seller for access, before you spend a day checking it by hand,
                and before you commit budget to a full review.
              </p>
              <p className="copy">What comes back tells you where that review should focus, not just whether to run one.</p>
              <a href="https://veritechdiligence.com/#contact" className="btn-secondary">
                Book the nine-layer review <span className="arrow">→</span>
              </a>
            </div>
          </div>
        </div>
      </section>

      <section className="access">
        <div className="outer">
          <div className="access-inner">
            <p className="eyebrow">Access</p>
            <h2>Veritech Site Checker is in early access.</h2>
            <p className="access-copy">
              Enter your email, we&rsquo;ll send you a sign-in link, and you can
              run your first scan right away &mdash; no invitation needed.
            </p>
            <div className="cta-row">
              <Link href="/login" className="btn-primary">
                Start a free scan <span className="arrow">→</span>
              </Link>
            </div>
          </div>
        </div>
      </section>

      <footer>
        <div className="outer">
          <p>Veritech Site Checker — a product of <a href="https://veritechdiligence.com">Veritech Diligence</a> {new Date().getFullYear()}.</p>
        </div>
      </footer>
    </div>
  );
}
