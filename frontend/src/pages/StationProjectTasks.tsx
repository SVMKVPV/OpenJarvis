import { useEffect, useState } from 'react';
import { fetchStationProjectTasks, type WorkspaceTask } from '../lib/api';

export function StationProjectTasks({ stationId, onOpenTask }: {
  stationId: string;
  onOpenTask: (folder: string, id: string) => void;
}) {
  const [tasks, setTasks] = useState<Array<WorkspaceTask & { folder: string }> | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const request = new AbortController();
    fetchStationProjectTasks(stationId, request.signal).then(
      (items) => { if (!request.signal.aborted) setTasks(items); },
      () => { if (!request.signal.aborted) setUnavailable(true); },
    );
    return () => request.abort();
  }, [stationId, refresh]);

  return <details className="station-details-editor">
    <summary>Assigned project tasks</summary>
    {unavailable ? <p role="status">Assigned project tasks are unavailable.</p>
      : !tasks ? <p role="status">Loading assigned project tasks.</p>
      : tasks.length === 0 ? <p>No tasks assigned to this workstation.</p>
      : <ul>{tasks.map((task) => (
        <li key={task.id}>
          <button type="button" onClick={() => onOpenTask(task.folder, task.id)}>{task.title}</button>
          <span> /{task.folder} · {task.completed ? 'Complete' : 'Open'}</span>
        </li>
      ))}</ul>}
    <button type="button" disabled={!unavailable && !tasks} onClick={() => {
      setUnavailable(false);
      setTasks(null);
      setRefresh((value) => value + 1);
    }}>Refresh assigned tasks</button>
  </details>;
}
