# 巨量星图直播达人微信字段调查

日期：2026-11-06  
平台：巨量星图 → 直播广场 → 达人详情  
样本达人：`7594043730697388068`（晓荷面部瑜伽1早上9.10分，当前账号可见微信）  
关联：[LIVE-03-wechat 卡片](../tasks/LIVE-03-wechat.md)

## 1. 真实页面路径

1. 打开 `https://www.xingtu.cn/ad/creator/author/douyin/<star_id>/10`。
2. hover 基本资料右侧「联系」。
3. 出现联系方式 popover，包含「查看微信」「在线沟通」「项目邀约」「电话沟通」；此处才出现微信入口。
4. 点击「查看微信」（不点复制图标、不点联系授权确认）。
5. 页面显示：

```html
<div role="dialog" aria-modal="true" aria-label="达人微信" class="el-dialog">
  <div class="el-dialog__header"><span class="el-dialog__title">达人微信</span></div>
  <div class="el-dialog__body">
    <div class="wechat">
      <微信号>
      <i class="star-icon star-icon-copy"></i>
    </div>
  </div>
</div>
```

6. 读取 `.el-dialog[aria-label="达人微信"] .wechat` 的文本，去掉复制图标的非文本内容；不点击复制。
7. 关闭弹窗，继续采集其他模块。

## 2. 权限与无数据

- 当前登录账号可见的样本达人能直接通过「查看微信」打开弹窗；未触发额外授权确认，也未绕过登录/付费控制。
- 「联系」hover 后若 popover 没有「查看微信」（例如 `7620474284346966052`），表示该达人无可用微信或当前账号无该入口；采集记 `NO_DATA`，不报错、不点击其他授权入口。
- 无微信达人仍能完整采集其他模块；实测 `7620474284346966052` 手动更新 COMPLETED、profile/pipeline complete、0 FAILED。
- 页面存在「获取达人联系方式」确认弹窗（联系授权），本字段不需要该弹窗；实现不点击「确定」，避免额外的联系方式授权/配额操作。

## 3. 数据来源选择

- 平台 `author_get_business_card_info` 响应也包含 `card_info.wechat`，但同响应还含 phone/email，且页面有独立联系方式授权弹窗。
- 为最小化敏感数据接触，**不注册、不解析、不持久化**该响应；只读取用户明确打开的 `达人微信` 弹窗文本。
- 复制按钮 `.star-icon-copy` 不点击；只取 `.wechat` 文本。

## 4. 值校验（脱敏）

- 样本值长度 11，SHA-256 前 8 位 `64862f5b`（完整值不写入本报告/日志）。
- 源页面弹窗、平台 card 响应、本系统快照、API、前端行四处 hash 一致。
- 提取正则：`^[A-Za-z0-9][A-Za-z0-9_-]{3,31}$`；拒绝「复制」「暂无数据」、空串和图标文本。

## 5. 证据

- 前端脱敏截图：[wechat-masked-basic.png](assets/LIVE-03-wechat/wechat-masked-basic.png)
- 原始值只保存在业务快照（不可变）及当前详情可读路径；不写入调试日志、报告或公开导出。
