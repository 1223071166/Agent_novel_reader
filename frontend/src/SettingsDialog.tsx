import { useEffect, useState } from "react";

import { loadAppSettings, saveAppSettings } from "./api";


type SettingsDialogProps = {
  onClose: () => void;
  onSaved: (showUsage: boolean) => void;
};

const MIN_TOOL_ROUNDS = 1;
const MAX_TOOL_ROUNDS = 100;

export default function SettingsDialog({ onClose, onSaved }: SettingsDialogProps) {
  const [toolRoundLimit, setToolRoundLimit] = useState("");
  const [showUsage, setShowUsage] = useState(true);
  const [modelProvider, setModelProvider] = useState<"siliconflow" | "custom">("siliconflow");
  const [siliconflowBaseUrl, setSiliconflowBaseUrl] = useState("");
  const [siliconflowModelName, setSiliconflowModelName] = useState("");
  const [siliconflowHasApiKey, setSiliconflowHasApiKey] = useState(false);
  const [siliconflowApiKey, setSiliconflowApiKey] = useState("");
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [customModelName, setCustomModelName] = useState("");
  const [customHasApiKey, setCustomHasApiKey] = useState(false);
  const [customApiKey, setCustomApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void loadAppSettings()
      .then((settings) => {
        if (active) {
          setToolRoundLimit(String(settings.tool_round_limit));
          setShowUsage(settings.show_usage);
          setModelProvider(settings.model_provider);
          setSiliconflowBaseUrl(settings.siliconflow.base_url);
          setSiliconflowModelName(settings.siliconflow.model_name);
          setSiliconflowHasApiKey(settings.siliconflow.has_api_key);
          setCustomBaseUrl(settings.custom.base_url);
          setCustomModelName(settings.custom.model_name);
          setCustomHasApiKey(settings.custom.has_api_key);
        }
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
    if (modelProvider === "siliconflow" && !siliconflowHasApiKey && !siliconflowApiKey.trim()) {
      setError("请填写硅基流动 API Key");
      return;
    }
    if (modelProvider === "custom") {
      if (!customBaseUrl.trim() || !customModelName.trim()) {
        setError("自定义配置需要填写 Base URL 和 Model Name");
        return;
      }
      if (!customHasApiKey && !customApiKey.trim()) {
        setError("请填写自定义 API Key");
        return;
      }
    }

    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const settings = await saveAppSettings({
        toolRoundLimit: value,
        showUsage,
        modelProvider,
        siliconflowApiKey: siliconflowApiKey.trim() || null,
        customBaseUrl,
        customModelName,
        customApiKey: customApiKey.trim() || null,
      });
      setToolRoundLimit(String(settings.tool_round_limit));
      setShowUsage(settings.show_usage);
      setModelProvider(settings.model_provider);
      setSiliconflowHasApiKey(settings.siliconflow.has_api_key);
      setCustomBaseUrl(settings.custom.base_url);
      setCustomModelName(settings.custom.model_name);
      setCustomHasApiKey(settings.custom.has_api_key);
      setSiliconflowApiKey("");
      setCustomApiKey("");
      onSaved(settings.show_usage);
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
              <span>每次回答工具调用轮数上限</span>
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

            <div className="settings-field">
              <span>显示本轮 Token 用量</span>
              <button
                type="button"
                className={`summary-switch settings-switch ${showUsage ? "enabled" : ""}`}
                aria-pressed={showUsage}
                disabled={saving}
                onClick={() => {
                  setShowUsage((previous) => !previous);
                  setSaved(false);
                  setError("");
                }}
              >
                <span />
              </button>
            </div>

            <label className="settings-field">
              <span>模型配置</span>
              <select
                value={modelProvider}
                disabled={saving}
                onChange={(event) => {
                  setModelProvider(event.target.value as "siliconflow" | "custom");
                  setSaved(false);
                  setError("");
                }}
              >
                <option value="siliconflow">硅基流动（默认）</option>
                <option value="custom">自定义</option>
              </select>
            </label>

            {modelProvider === "siliconflow" ? (
              <div className="model-settings">
                <div><span>Base URL</span><code>{siliconflowBaseUrl}</code></div>
                <div><span>Model</span><code>{siliconflowModelName}</code></div>
                <label>
                  <span>API Key</span>
                  <input
                    type="password"
                    value={siliconflowApiKey}
                    disabled={saving}
                    autoComplete="new-password"
                    placeholder={siliconflowHasApiKey ? "已保存，留空不修改" : "请输入 API Key"}
                    onChange={(event) => {
                      setSiliconflowApiKey(event.target.value);
                      setSaved(false);
                      setError("");
                    }}
                  />
                </label>
              </div>
            ) : (
              <div className="model-settings">
                <label>
                  <span>Base URL</span>
                  <input
                    value={customBaseUrl}
                    disabled={saving}
                    placeholder="https://example.com/v1"
                    onChange={(event) => {
                      setCustomBaseUrl(event.target.value);
                      setSaved(false);
                      setError("");
                    }}
                  />
                </label>
                <label>
                  <span>Model Name</span>
                  <input
                    value={customModelName}
                    disabled={saving}
                    placeholder="provider/model-name"
                    onChange={(event) => {
                      setCustomModelName(event.target.value);
                      setSaved(false);
                      setError("");
                    }}
                  />
                </label>
                <label>
                  <span>API Key</span>
                  <input
                    type="password"
                    value={customApiKey}
                    disabled={saving}
                    autoComplete="new-password"
                    placeholder={customHasApiKey ? "已保存，留空不修改" : "请输入 API Key"}
                    onChange={(event) => {
                      setCustomApiKey(event.target.value);
                      setSaved(false);
                      setError("");
                    }}
                  />
                </label>
              </div>
            )}

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
