"""
Aipply - Application Tracker

Tracks job applications, stores data in JSON, and generates HTML/XLSX reports.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class ApplicationTracker:
    """Tracks job applications and generates reports."""

    def __init__(self, tracker_path: str = "output/tracker.json"):
        self.tracker_path = Path(tracker_path)
        self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
        self.applications = self._load()

    def _load(self) -> list:
        """Load existing applications from JSON file."""
        if self.tracker_path.exists():
            try:
                with open(self.tracker_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return []
        return []

    def _save(self):
        """Save applications to JSON file."""
        with open(self.tracker_path, "w") as f:
            json.dump(self.applications, f, indent=2, default=str)

    def add_application(
        self,
        company: str,
        position: str,
        job_url: str,
        location: str = "",
        status: str = "applied",
        resume_path: str = "",
        cover_letter_path: str = "",
        job_description: str = "",
        jd_file_path: str = "",
        notes: str = "",
    ) -> dict:
        """Record a new job application."""
        # Convert all paths to absolute for file:// links
        if resume_path:
            resume_path = str(Path(resume_path).resolve())
        if cover_letter_path:
            cover_letter_path = str(Path(cover_letter_path).resolve())
        if jd_file_path:
            jd_file_path = str(Path(jd_file_path).resolve())

        application = {
            "id": len(self.applications) + 1,
            "company": company,
            "position": position,
            "job_url": job_url,
            "location": location,
            "status": status,
            "resume_path": resume_path,
            "cover_letter_path": cover_letter_path,
            "jd_file_path": jd_file_path,
            "job_description": job_description,
            "notes": notes,
            "applied_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        self.applications.append(application)
        self._save()
        return application

    def update_status(self, app_id: int, status: str, notes: str = ""):
        """Update the status of an application."""
        for app in self.applications:
            if app["id"] == app_id:
                app["status"] = status
                app["updated_at"] = datetime.now().isoformat()
                if notes:
                    app["notes"] = notes
                self._save()
                return app
        return None

    def get_applications(self, status: Optional[str] = None) -> list:
        """Get all applications, optionally filtered by status."""
        if status:
            return [a for a in self.applications if a["status"] == status]
        return self.applications

    def is_already_applied(self, job_url: str) -> bool:
        """Check if we've already applied to this job."""
        return any(a["job_url"] == job_url for a in self.applications)

    def get_stats(self) -> dict:
        """Get application statistics."""
        total = len(self.applications)
        by_status = {}
        by_company = {}
        for app in self.applications:
            status = app["status"]
            company = app["company"]
            by_status[status] = by_status.get(status, 0) + 1
            by_company[company] = by_company.get(company, 0) + 1
        return {
            "total": total,
            "by_status": by_status,
            "by_company": by_company,
        }

    def generate_html_report(self, output_path: str = "output/reports/report.html") -> str:
        """Generate an HTML report of all applications."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        stats = self.get_stats()

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aipply - Application Tracker Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5; color: #333; padding: 2rem;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: #1a1a2e; margin-bottom: 0.5rem; font-size: 2rem; }}
        .subtitle {{ color: #666; margin-bottom: 2rem; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem; margin-bottom: 2rem;
        }}
        .stat-card {{
            background: white; padding: 1.5rem; border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        .stat-card h3 {{
            color: #666; font-size: 0.85rem;
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        .stat-card .value {{ font-size: 2rem; font-weight: 700; color: #1a1a2e; }}
        table {{
            width: 100%; background: white; border-radius: 12px;
            overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            border-collapse: collapse;
        }}
        th {{
            background: #1a1a2e; color: white; padding: 1rem;
            text-align: left; font-size: 0.85rem;
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        td {{ padding: 0.875rem 1rem; border-bottom: 1px solid #eee; }}
        tr:hover td {{ background: #f8f9fa; }}
        .status {{
            padding: 0.25rem 0.75rem; border-radius: 20px;
            font-size: 0.8rem; font-weight: 600; display: inline-block;
        }}
        .status-applied {{ background: #e3f2fd; color: #1565c0; }}
        .status-interview {{ background: #e8f5e9; color: #2e7d32; }}
        .status-rejected {{ background: #fce4ec; color: #c62828; }}
        .status-offered {{ background: #fff3e0; color: #e65100; }}
        a {{ color: #1565c0; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .generated {{ text-align: center; color: #999; margin-top: 2rem; font-size: 0.85rem; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📋 Aipply - Application Tracker</h1>
        <p class="subtitle">Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>

        <div class="stats">
            <div class="stat-card">
                <h3>Total Applications</h3>
                <div class="value">{stats['total']}</div>
            </div>
"""

        # Add status cards
        for status, count in stats.get('by_status', {}).items():
            html += f"""
            <div class="stat-card">
                <h3>{status.title()}</h3>
                <div class="value">{count}</div>
            </div>
"""

        html += """
        </div>

        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Company</th>
                    <th>Position</th>
                    <th>Location</th>
                    <th>Status</th>
                    <th>Applied</th>
                    <th>Job Link</th>
                    <th>Resume</th>
                    <th>Cover Letter</th>
                    <th>Job Description</th>
                </tr>
            </thead>
            <tbody>
"""

        # Resolve project root for making relative web paths
        project_root = str(Path(self.tracker_path).resolve().parent.parent)

        for app in sorted(self.applications, key=lambda x: x['applied_at'], reverse=True):
            status_class = f"status-{app['status'].lower().replace(' ', '-').replace('_', '-')}"
            applied_date = datetime.fromisoformat(app['applied_at']).strftime('%m/%d/%Y %I:%M %p')

            def _rel(abs_path):
                if not abs_path:
                    return ''
                return abs_path.replace(project_root + '/', '').replace(project_root, '')

            rp = _rel(app.get('resume_path', ''))
            resume_link = f'<a href="/download/{rp}">📄 Resume</a>' if rp else '—'

            cp = _rel(app.get('cover_letter_path', ''))
            cl_link = f'<a href="/download/{cp}">✉️ Cover Letter</a>' if cp else '—'

            jd = _rel(app.get('jd_file_path', ''))
            jd_link = f'<a href="/view/{jd}">📝 View JD</a>' if jd else '—'

            html += f"""
                <tr>
                    <td>{app['id']}</td>
                    <td><strong>{app['company']}</strong></td>
                    <td>{app['position']}</td>
                    <td>{app['location']}</td>
                    <td><span class="status {status_class}">{app['status'].replace('_',' ').title()}</span></td>
                    <td>{applied_date}</td>
                    <td><a href="{app['job_url']}" target="_blank">🔗 Job Post</a></td>
                    <td>{resume_link}</td>
                    <td>{cl_link}</td>
                    <td>{jd_link}</td>
                </tr>
"""

        html += f"""
            </tbody>
        </table>
        <p class="generated">Generated by Aipply | {datetime.now().year}</p>
    </div>
</body>
</html>"""

        with open(output, "w") as f:
            f.write(html)

        return str(output)
