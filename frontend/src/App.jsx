import { useState, useEffect } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

function App() {
  const [statusData, setStatusData] = useState(null);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(`${API_BASE}/live-status`);
        const data = await res.json();
        setStatusData(data);
      } catch (err) {
        console.error("Failed to fetch status", err);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-container">
      <nav style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '3rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border-color)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ width: '32px', height: '32px', background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
          </div>
          <h1 style={{ fontSize: '1.25rem', fontWeight: 600, letterSpacing: '0.05em', color: 'var(--text-primary)' }}>SYNC<span style={{ color: 'var(--text-secondary)' }}>FLOW</span></h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {statusData && (
             <div className="status-badge" style={{ background: 'rgba(16, 185, 129, 0.1)', color: 'var(--success-color)' }}>
                <span className="status-indicator"></span>
                System Active
             </div>
          )}
        </div>
      </nav>

      {statusData && (
        <div className="glass-panel" style={{ padding: '2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '2rem' }}>
            <div>
              <h2 style={{ fontSize: '1.25rem', marginBottom: '0.25rem' }}>Inbox Monitor</h2>
              <p className="text-sub">Real-time pipeline analytics</p>
            </div>
            <div className="text-sub" style={{ fontSize: '0.85rem' }}>
              Last sync: {statusData.last_scan ? new Date(statusData.last_scan).toLocaleString() : 'Never'}
            </div>
          </div>

          <table style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>Event Details</th>
                <th>Processing Status</th>
                <th>Action Log</th>
              </tr>
            </thead>
            <tbody>
              {statusData.emails.map(email => (
                <tr key={email.email_id} className={email.status === 'deleted' ? 'opacity-50' : ''}>
                  <td>
                    <strong style={{ display: 'block', fontSize: '1rem', marginBottom: '0.25rem' }}>{email.subject || email.email_id}</strong>
                    <div className="text-sub" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                       <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                       {email.from}
                    </div>
                    {email.meeting && email.meeting.meeting_title && (
                      <div style={{ marginTop: '0.75rem', padding: '0.5rem', background: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                        <span style={{ color: 'var(--accent-color)', fontWeight: 500 }}>{email.meeting.meeting_title}</span>
                        <div className="text-sub" style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>
                           {email.meeting.date} {email.meeting.time} {email.meeting.time_zone ? `(${email.meeting.time_zone})` : ''}
                        </div>
                      </div>
                    )}
                  </td>
                  <td style={{ verticalAlign: 'middle' }}>
                    <span className={`status-badge badge-${email.status}`}>
                      {email.status.charAt(0).toUpperCase() + email.status.slice(1)}
                    </span>
                  </td>
                  <td className="text-sub" style={{ verticalAlign: 'middle' }}>
                    {email.reason || 'Processed successfully'}
                    {email.link && (
                      <div style={{ marginTop: '0.5rem' }}>
                        <a href={email.link} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-color)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                          Open Calendar
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                        </a>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {statusData.emails.length === 0 && (
                <tr><td colSpan="3" style={{ textAlign: 'center', padding: '2rem' }}>No activity detected in the current session.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <PendingReviewSection />
    </div>
  );
}

function PendingReviewSection() {
  const [pending, setPending] = useState([]);

  const fetchPending = async () => {
    try {
      const res = await fetch(`${API_BASE}/pending-meetings`);
      const data = await res.json();
      setPending(data);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchPending();
    const interval = setInterval(fetchPending, 5000);
    return () => clearInterval(interval);
  }, []);

  if (pending.length === 0) return null;

  return (
    <div className="glass-panel" style={{ border: '1px solid rgba(245, 158, 11, 0.4)', marginTop: '2rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.5rem' }}>
         <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--warning-color)" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
         <h2 style={{ margin: 0, color: 'var(--warning-color)' }}>Action Required</h2>
      </div>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', gap: '1.5rem' }}>
        {pending.map(item => (
          <PendingCard key={item.email_id} item={item} onComplete={fetchPending} />
        ))}
      </div>
    </div>
  );
}

function PendingCard({ item, onComplete }) {
  const [formData, setFormData] = useState({
    meeting_title: item.extracted_data?.meeting_title || '',
    date: item.extracted_data?.date || '',
    time: item.extracted_data?.time || '',
    meet_link: item.extracted_data?.meet_link || '',
  });

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleApprove = async () => {
    try {
      // Force time_zone to empty string so the backend interprets the date/time exactly as local time
      const payload = { ...formData, time_zone: '' };
      await fetch(`${API_BASE}/approve-meeting/${item.email_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      onComplete();
    } catch (err) { alert(err); }
  };

  const handleRetry = async () => {
    try {
      await fetch(`${API_BASE}/pending-meetings/${item.email_id}/retry`, { method: 'POST' });
      onComplete();
    } catch (err) { alert(err); }
  };

  const handleDismiss = async () => {
    try {
      await fetch(`${API_BASE}/pending-meetings/${item.email_id}`, { method: 'DELETE' });
      onComplete();
    } catch (err) { alert(err); }
  };

  return (
    <div className="pending-card" style={{ padding: '1.5rem', borderRadius: 'var(--radius-lg)' }}>
      <h3 style={{ marginBottom: '0.25rem', fontSize: '1.1rem' }}>{item.subject}</h3>
      <p className="text-sub" style={{ marginBottom: '1.5rem', fontSize: '0.8rem' }}>ID: {item.email_id.substring(0,8)}...</p>
      
      <div className="form-group">
        <label>Title</label>
        <input name="meeting_title" value={formData.meeting_title} onChange={handleChange} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
        <div className="form-group">
          <label>Date (YYYY-MM-DD)</label>
          <input name="date" value={formData.date} onChange={handleChange} />
        </div>
        <div className="form-group">
          <label>Time (HH:MM AM/PM)</label>
          <input name="time" value={formData.time} onChange={handleChange} />
        </div>
      </div>
      <div className="form-group">
        <label>Meet Link</label>
        <input name="meet_link" value={formData.meet_link} onChange={handleChange} />
      </div>

      <div className="btn-group" style={{ marginTop: '2rem' }}>
        <button className="btn-primary" style={{ flex: 1 }} onClick={handleApprove}>Approve</button>
        <button className="btn-secondary" style={{ flex: 1 }} onClick={handleRetry}>Retry AI</button>
        <button className="btn-danger" style={{ flex: 1 }} onClick={handleDismiss}>Dismiss</button>
      </div>
    </div>
  );
}

export default App;
