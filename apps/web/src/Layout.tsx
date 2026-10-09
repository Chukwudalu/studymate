import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { listSubjects } from "./api";
import { useAuth } from "./AuthContext";

export default function Layout() {
  const [subjects, setSubjects] = useState<string[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const { signOut } = useAuth();

  useEffect(() => {
    listSubjects().then(setSubjects).catch(() => {});
    setMenuOpen(false);
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <header className="mobile-bar">
        <NavLink className="word" to="/">study<span>mate</span></NavLink>
        <button
          className="btn btn-ghost menu-btn"
          type="button"
          aria-expanded={menuOpen}
          aria-controls="sidebar"
          onClick={() => setMenuOpen((o) => !o)}
        >
          {menuOpen ? "Close" : "Menu"}
        </button>
      </header>

      {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} />}

      <aside id="sidebar" className={"sidebar" + (menuOpen ? " open" : "")}>
        <NavLink className="word" to="/">study<span>mate</span></NavLink>

        <NavLink to="/" className="btn btn-primary sidebar-upload" end>
          + New lecture
        </NavLink>

        <nav className="subject-nav">
          <span className="section-label">Subjects</span>
          {subjects.length === 0 && (
            <span className="sidebar-empty">No subjects yet</span>
          )}
          {subjects.map((s) => (
            <NavLink
              key={s}
              to={`/subject/${encodeURIComponent(s)}`}
              className={({ isActive }) => "subject-link" + (isActive ? " active" : "")}
            >
              {s}
            </NavLink>
          ))}
        </nav>

        <button className="btn btn-ghost" type="button" onClick={signOut}>
          Sign out
        </button>
      </aside>

      <main className="main-area">
        <Outlet />
      </main>
    </div>
  );
}
