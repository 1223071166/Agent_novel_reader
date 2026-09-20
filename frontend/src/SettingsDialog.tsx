import { useEffect, useState } from "react";

import { loadAppSettings, saveAppSettings } from "./api";


type SettingsDialogProps = {
  onClose: () => void;
};

const MIN_TOOL_ROUNDS = 1;
const MAX_TOOL_ROUNDS = 100;

export default function SettingsDialog({ onClose }: SettingsDialogProps) {
  const [toolRoundLimit, setToolRoundLimit] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void loadAppSettings()
      .then((settings) => {
        if (active) setToolRoundLimit(String(settings.tool_round_limit));
      })
      .catch((requestError) => {
        if (active) {
          setError(requestError instanceof Error ? requestError.message : "加载设置失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const save = async () => {
    const value = Number(toolRoundLimit);
    if (!Number.isInteger(value) || value < MIN_TOOL_ROUNDS || value > MAX_TOOL_ROUNDS) {
      setError(`工具调用轮数必须是 ${MIN_TOOL_ROUNDS}-${MAX_TOOL_ROUNDS} 之间的整数`);
      return;
    }

    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const settings = await saveAppSettings(value);
      setToolRoundLimit(String(settings.tool_round_limit));
      setSaved(true);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "保存设置失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="import-overlay" role="presentation">
      <section className="import-dialog settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="import-header">
          <div>
            <h2 id="settings-title">设置</h2>
          </div>
          <button className="import-close" type="button" aria-label="关闭设置" onClick={onClose}>×</button>
        </div>

        {loading ? (
          <div className="settings-loading">加载中…</div>
        ) : (
          <div className="settings-form">
            <label className="settings-field">
              <span>工具调用轮数上限</span>
              <input
                type="number"
                min={MIN_TOOL_ROUNDS}
                max={MAX_TOOL_ROUNDS}
                step="1"
                value={toolRoundLimit}
                disabled={saving}
                onChange={(event) => {
                  setToolRoundLimit(event.target.value);
                  setSaved(false);
                  setError("");
                }}
              />
            </label>

            {error && <div className="import-error">{error}</div>}
            <div className="settings-actions">
              {saved ? <span>已保存</span> : <span />}
              <button className="import-primary" type="button" disabled={saving} onClick={() => void save()}>
                {saving ? "保存中…" : "保存设置"}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
