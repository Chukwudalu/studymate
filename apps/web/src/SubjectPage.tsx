import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { listLectures } from "./api";
import type { LectureSummary } from "./types";
import { statusPillClass, formatDate } from "./utils";

export default function SubjectPage() {
  const { name } = useParams<{ name: string }>();
  const subject = name ? decodeURIComponent(name) : "";
  const [lectures, setLectures] = useState<LectureSummary[]>([]);

  useEffect(() => {
    if (!subject) return;
    listLectures(subject).then(setLectures).catch(() => {});
  }, [subject]);

  const byDate = groupByDate(lectures);

  return (
    <div className="wrap">
      <div className="masthead">
        <h1 className="display" style={{ fontSize: 26 }}>{subject}</h1>
        <Link className="btn btn-ghost" to="/">+ New lecture</Link>
      </div>

      <section className="card">
        {lectures.length === 0 && <p className="lede">No lectures yet in this subject.</p>}
        {Object.entries(byDate).map(([date, items]) => (
          <div key={date} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="section-label" style={{ fontSize: 10 }}>{date}</span>
            <div className="lecture-list">
              {items.map((l) => (
                <Link key={l.lecture_id} className="lecture-row" to={`/lecture/${l.lecture_id}`}>
                  <span>{l.lecture_id.slice(0, 8)}</span>
                  <span className={statusPillClass(l.status)}>
                    <span className="pill-dot" />
                    {l.status}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

function groupByDate(lectures: LectureSummary[]): Record<string, LectureSummary[]> {
  const result: Record<string, LectureSummary[]> = {};
  for (const lecture of lectures) {
    const date = formatDate(lecture.created_at);
    result[date] ??= [];
    result[date].push(lecture);
  }
  return result;
}
