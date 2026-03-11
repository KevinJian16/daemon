# Portal Backend Gaps

更新日期：2026-03-11

## 已确认缺口

1. `Folio` 卷内对话缺少后端路由
   - 前端已预留 Claude 式卷内对话区。
   - 但当前没有 `folio messages` / `folio message` 类 route。
   - 结果：`Folio` 页只能停在静态壳和真实对象数据，不能真正发消息。

2. `Deed` 当前阶段页 / 比较页缺少后端机制
   - 真实数据里已经出现 `awaiting_eval` 状态。
   - 但当前没有：
     - 当前阶段页数据接口
     - 候选版本列表接口
     - 版本比较与保留接口
     - 评价确认 / 改选版本联动接口
   - 结果：`Slip` 页只能显示最近一次 `Deed` 卡，不能进入正式比较流程。

3. 材料上传缺少 Portal 后端入口
   - 前端已保留 Claude 式附件入口。
   - 但当前 `Slip` / `Folio` 只接文字补记，没有材料集写入口。
   - 结果：上传按钮只能保留壳，不能真正落材料。

4. Portal 新建入口缺少后端路由
   - 当前没有从 `Portal` 直接新建 `Draft / Slip / Folio` 的后端接口。
   - 结果：左栏“新建”只能停在禁用态。

## 已接通并在前端落位

- `GET /portal-api/sidebar`
- `GET /portal-api/slips/{slip_slug}`
- `GET /portal-api/slips/{slip_slug}/messages`
- `POST /portal-api/slips/{slip_slug}/message`
- `POST /portal-api/slips/{slip_slug}/rerun`
- `POST /portal-api/slips/{slip_slug}/copy`
- `POST /portal-api/slips/{slip_slug}/take-out`
- `GET /portal-api/slips/{slip_slug}/result/files`
- `PUT /portal-api/slips/{slip_slug}/cadence`
- `DELETE /portal-api/slips/{slip_slug}/cadence`
- `GET /portal-api/folios/{folio_slug}`
- `POST /portal-api/folios/{folio_slug}/reorder`

## 未做破坏性联调的项

- `copy slip`
  - 前端已接按钮。
  - 这次没有直接点真实数据，避免在你当前工作区里额外制造副本。

- `take out slip`
  - 前端已接按钮。
  - 当前样本里没有卷内 `Slip` 可安全演练。

- `folio reorder`
  - 前端整理模式和提交接口已接好。
  - 当前样本卷是空卷，没有实际顺序可提交验证。
