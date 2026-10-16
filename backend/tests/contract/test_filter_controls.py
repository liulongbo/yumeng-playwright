"""Synthetic DOM contracts for the Xingtu v2 compound filter executor.

The markup mirrors only the registered, already-evidenced component surfaces.  It never contacts
Xingtu.  In particular, the profile select removes its input placeholder after a multi-selection,
which is the Element UI re-render that previously shifted input-based indexes.
"""

# ruff: noqa: E501 -- keeping the synthetic HTML rows intact makes the component shape readable.

from pathlib import Path

from playwright.async_api import async_playwright
from xingtu.adapter import BrowserAdapter
from xingtu.contracts import PlatformRegistry
from xingtu.intake import build_expected_plan
from xingtu.product_models import RequirementForm


def registry() -> PlatformRegistry:
    current = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    return current.model_copy(update={"action_interval_seconds": 0.001})


async def guard() -> None:
    return None


PROFILE_HTML = """
<div class="search-content--selected-filters">已选条件</div>
<div class="author-image-select">
  <div class="xt-dropdown">观众画像 <span role="button" onclick="openProfile()">观众画像</span></div>
</div>
<div id="profile" class="el-popper" style="display:none">
  <div class="dimension"><span onclick="closeMenu()">观众年龄</span><div class="el-select" onclick="openMenu(0)"><input placeholder="请选择"></div></div>
  <div class="dimension"><span onclick="closeMenu()">观众性别</span><div class="el-select" onclick="openMenu(1)"><input placeholder="请选择"></div></div>
  <div class="dimension"><span onclick="closeMenu()">观众设备品牌</span><div class="el-select" onclick="openMenu(2)"><input placeholder="请选择"></div></div>
  <div class="dimension"><span onclick="closeMenu()">观众地域</span><div class="el-select" onclick="openMenu(3)"><input placeholder="请选择"></div></div>
  <div class="dimension"><span onclick="closeMenu()">观众八大人群</span><div class="el-select" onclick="openMenu(4)"><input placeholder="请选择"></div></div>
  <button onclick="confirmProfile()">确定</button>
</div>
<div id="menu" class="el-select-dropdown" style="display:none">
  <span onclick="choose(this)">18-23岁居多</span><span onclick="choose(this)">24-30岁居多</span>
  <span onclick="choose(this)">男性占比大于70%</span>
  <span onclick="choose(this)">苹果居多</span><span onclick="choose(this)">华为居多</span>
  <span onclick="choose(this)">一线城市居多</span><span onclick="choose(this)">二线城市居多</span>
  <span onclick="choose(this)">Z世代</span><span onclick="choose(this)">新锐白领</span>
</div>
<script>
let dimension = 0;
const selected = [];
function openProfile() { document.querySelector('#profile').style.display = 'block'; }
function openMenu(index) { dimension = index; document.querySelector('#menu').style.display = 'block'; }
function closeMenu() { document.querySelector('#menu').style.display = 'none'; }
function choose(node) {
  selected.push(node.textContent);
  // Real Element UI clears this placeholder once the multi-select owns a tag.
  document.querySelectorAll('#profile .el-select input')[dimension].removeAttribute('placeholder');
}
function confirmProfile() {
  closeMenu();
  document.querySelector('#profile').style.display = 'none';
  document.querySelector('.search-content--selected-filters').textContent = selected.join(' ');
}
</script>
"""


FOLLOWERS_HTML = """
<div class="search-content--selected-filters">已选条件</div>
<div class="star-select"><span role="button" onclick="openFollowers()">粉丝量级</span></div>
<ul id="followers" class="el-dropdown-menu el-popper" style="display:none">
  <div class="custom">
    <input placeholder="0"><input placeholder="5000">
    <button class="submit-btn" onclick="confirmFollowers()">确定</button>
  </div>
</ul>
<script>
function openFollowers() { document.querySelector('#followers').style.display = 'block'; }
function confirmFollowers() {
  const inputs = document.querySelectorAll('#followers input');
  document.querySelector('.search-content--selected-filters').textContent =
    `粉丝数量：${inputs[0].value}w-${inputs[1].value}w`;
  document.querySelector('#followers').style.display = 'none';
}
</script>
"""


async def test_profile_dimensions_keep_their_identity_after_placeholder_re_render():
    current = registry()
    form = RequirementForm(
        viewer_profile={
            "age": ["age_18_23", "age_24_30"],
            "gender": "male_70",
            "device_brand": ["apple", "huawei"],
            "city_level": ["tier_1", "tier_2"],
            "crowd": ["gen_z", "new_white_collar"],
        }
    )
    plan = build_expected_plan(form, current.capabilities)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_content(PROFILE_HTML)
        adapter = BrowserAdapter(context, current, "account", guard, live=False)

        await adapter.apply_xingtu_filters(page, plan)

        selected = await page.locator(".search-content--selected-filters").inner_text()
        for label in (
            "18-23岁居多",
            "24-30岁居多",
            "男性占比大于70%",
            "苹果居多",
            "华为居多",
            "一线城市居多",
            "二线城市居多",
            "Z世代",
            "新锐白领",
        ):
            assert label in selected
        await browser.close()


async def test_followers_custom_uses_inline_inputs_without_inventing_a_menu_item():
    current = registry()
    plan = build_expected_plan(
        RequirementForm(followers={"min": 12.5, "max": 25.5}), current.capabilities
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_content(FOLLOWERS_HTML)
        adapter = BrowserAdapter(context, current, "account", guard, live=False)

        await adapter.apply_xingtu_filters(page, plan)

        assert (
            await page.locator(".search-content--selected-filters").inner_text()
            == "粉丝数量：12.5w-25.5w"
        )
        await browser.close()
