import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, LoaderCircle, ShieldCheck, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { api, ApiError } from "./api";
import { formatDate, shortId, statusLabel } from "./status";
import type { CreatorScene, CreatorUpdateServiceView } from "./types";
import { ErrorState, LoadingState, PageHeader } from "./ui";

const platformLabel = { douyin_xingtu: "巨量星图", kuaishou_juxing: "磁力聚星" } as const;
const sceneLabel: Record<CreatorScene, string> = {
  video_square: "短视频广场",
  live_square: "直播广场",
};
const unavailableLabel: Record<string, string> = {
  SCHEDULER_NOT_RUNNING: "调度器未运行",
  SERVICE_CONFIG_MISSING: "缺少服务配置",
  UPDATE_VIDEO_REGISTRY_UNAVAILABLE: "平台短视频契约不可用",
  UPDATE_LIVE_REGISTRY_UNAVAILABLE: "平台直播契约不可用",
  SCOPE_NOT_REPORTED: "调度器未报告该服务",
};

function groupKey(item: CreatorUpdateServiceView) {
  return `${item.platform}:${item.creator_scene}`;
}

function effectiveState(item: CreatorUpdateServiceView) {
  if (!item.enabled) return { text: "已关闭", tone: "off" };
  if (item.effective_enabled) return { text: "生效中", tone: "on" };
  if (!item.scheduler_alive) return { text: "等待调度器", tone: "wait" };
  if (item.registry_available === false) return { text: "契约不可用", tone: "danger" };
  return { text: "未生效", tone: "wait" };
}

function actionError(error: unknown) {
  if (error instanceof ApiError) return error.detail.message || "开关保存失败，请重试。";
  return "开关保存失败，请重试。";
}

export function UpdateServicesPage() {
  const queryClient = useQueryClient();
  const services = useQuery({
    queryKey: ["update-services"],
    queryFn: api.updateServices,
    refetchInterval: 10_000,
  });
  const toggle = useMutation({
    mutationFn: ({ item, enabled }: { item: CreatorUpdateServiceView; enabled: boolean }) =>
      api.setUpdateService(item.platform, item.creator_scene, enabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["update-services"] });
    },
  });
  if (services.isLoading) {
    return <div className="page-wrap"><LoadingState label="正在读取自动更新服务" /></div>;
  }
  if (services.isError || !services.data) {
    return <div className="page-wrap"><ErrorState error={services.error} retry={() => services.refetch()} /></div>;
  }
  const items = services.data.items;
  const schedulerAlive = services.data.scheduler_alive;
  const enabledCount = items.filter((item) => item.enabled).length;
  const effectiveCount = items.filter((item) => item.effective_enabled).length;
  const dueCount = items.reduce((total, item) => total + item.due_count, 0);
  const inFlightCount = items.reduce((total, item) => total + item.in_flight_count, 0);
  const pendingKey = toggle.isPending && toggle.variables ? groupKey(toggle.variables.item) : null;
  return <div className="page-wrap">
    <PageHeader
      eyebrow="AUTOMATION CONTROL"
      title="自动更新服务"
      description="按平台与达人场景分别管理已入库达人的定时资料更新。关闭只停止新的自动更新，不影响手动更新和正常采集。"
    />
    <section className={`update-scheduler-banner ${schedulerAlive ? "online" : "offline"}`}>
      {schedulerAlive ? <ShieldCheck size={20} /> : <TriangleAlert size={20} />}
      <div>
        <strong>{schedulerAlive ? "调度器在线" : "调度器未运行"}</strong>
        <span>
          {schedulerAlive
            ? `最近心跳 ${formatDate(services.data.scheduler_last_tick_at)}；只有「分组开启 + 调度器在线 + 契约可用」时才会创建自动更新任务。`
            : "分组开关仍会保存，但在调度器进程启动前不会创建任何自动更新任务。"}
        </span>
      </div>
    </section>
    <section className="unit-summary-grid">
      <div className="panel"><span>已开启分组</span><strong>{enabledCount} / {items.length}</strong></div>
      <div className="panel"><span>当前生效</span><strong>{effectiveCount}</strong></div>
      <div className="panel"><span>到期待更新</span><strong>{dueCount}</strong></div>
      <div className="panel"><span>执行中批次</span><strong>{inFlightCount}</strong></div>
    </section>
    <section className="panel unit-table-wrap">
      <table className="unit-table update-service-table">
        <thead>
          <tr>
            <th>平台 / 场景</th>
            <th>自动更新</th>
            <th>当前生效</th>
            <th>下次计划</th>
            <th>最近成功</th>
            <th>最近任务</th>
            <th>计划 / 到期 / 执行</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const key = groupKey(item);
            const state = effectiveState(item);
            const unavailable = item.unavailable_reason
              ? unavailableLabel[item.unavailable_reason] || item.unavailable_reason
              : null;
            return <tr key={key}>
              <td>
                <strong>{platformLabel[item.platform]}</strong>
                <small>{sceneLabel[item.creator_scene]}</small>
              </td>
              <td>
                <div className="update-switch-cell">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={item.enabled}
                    aria-label={`${item.enabled ? "关闭" : "开启"} ${platformLabel[item.platform]}${sceneLabel[item.creator_scene]}自动更新`}
                    className={`switch ${item.enabled ? "switch-on" : ""}`}
                    disabled={pendingKey === key}
                    onClick={() => toggle.mutate({ item, enabled: !item.enabled })}
                  >
                    <span className="switch-track"><span className="switch-thumb" /></span>
                  </button>
                  <span>{pendingKey === key ? <><LoaderCircle className="spin" size={13} />保存中</> : item.enabled ? "已开启" : "已关闭"}</span>
                </div>
              </td>
              <td>
                <span className={`update-state ${state.tone}`}>{state.text}</span>
                {unavailable && <small>{unavailable}</small>}
              </td>
              <td>
                {item.next_due_at ? <><b>{formatDate(item.next_due_at)}</b>{!item.enabled && <small>已关闭，不会执行</small>}</> : <span>尚未纳入计划</span>}
              </td>
              <td>
                <b>{item.last_success_at ? formatDate(item.last_success_at) : "—"}</b>
                {item.last_attempt_at && <small>最近尝试 {formatDate(item.last_attempt_at)}</small>}
              </td>
              <td>
                {item.last_task
                  ? <><Link to={`/tasks/${item.last_task.root_task_id}`}>{shortId(item.last_task.root_task_id)}<ChevronRight size={12} /></Link><small>{statusLabel[item.last_task.state]} · {item.last_task.valid_count}/{item.last_task.target_count} 位 · 完整 {item.last_task.profile_complete_count}</small>{item.last_task.failure_reason && <small>{item.last_task.failure_reason}</small>}</>
                  : <span>暂无</span>}
              </td>
              <td>
                <b>{item.enrolled_count} / {item.due_count} / {item.in_flight_count}</b>
                <small>已纳入 / 到期未执行 / 执行中</small>
                {item.missing_target_count > 0 && <small className="update-warning">{item.missing_target_count} 位缺少详情定位，暂未纳入</small>}
              </td>
            </tr>;
          })}
        </tbody>
      </table>
    </section>
    <p className="update-service-note">
      已加入计划但尚未开始的批次，在分组关闭后会于开始执行前取消；已在执行的批次会按现有租约与结算规则正常完成。
      普通采集与手动更新不受这些开关影响。
    </p>
    {toggle.isError && <div className="form-error" role="alert">{actionError(toggle.error)}</div>}
  </div>;
}
