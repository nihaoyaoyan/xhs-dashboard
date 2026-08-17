(function () {
  function parseDate(value) {
    if (!value) return null;
    const date = new Date(`${value}T00:00:00`);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function isoDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function daysAgo(latestDate, days) {
    const date = new Date(latestDate);
    date.setDate(date.getDate() - (days - 1));
    return date;
  }

  function computeRange(preset, dates) {
    if (!dates.length) return { start: "", end: "" };
    const first = parseDate(dates[0]);
    const latest = parseDate(dates[dates.length - 1]);
    if (!first || !latest) return { start: "", end: "" };
    const year = latest.getFullYear();
    const month = latest.getMonth();
    const quarterStartMonth = Math.floor(month / 3) * 3;
    let start = first;
    if (preset === "7D") start = daysAgo(latest, 7);
    if (preset === "30D") start = daysAgo(latest, 30);
    if (preset === "MTD") start = new Date(year, month, 1);
    if (preset === "QTD") start = new Date(year, quarterStartMonth, 1);
    if (preset === "YTD") start = new Date(year, 0, 1);
    if (start < first || preset === "ALL") start = first;
    return { start: isoDate(start), end: isoDate(latest) };
  }

  function withinRange(row, state) {
    const value = row.date || row.snapshot_date;
    if (!value) return true;
    if (state.start && value < state.start) return false;
    if (state.end && value > state.end) return false;
    return true;
  }

  window.setupDashboardRuntime = function setupDashboardRuntime(config) {
    const chartFactories = config.chartFactories || {};
    const sourceMap = config.sourceMap || {};
    const tables = config.tables || {};
    const allDates = (config.availableDates || []).slice().sort();
    const productFilter = config.productFilter || {};
    const productField = productFilter.field || null;
    const productOptions = productFilter.options || [];
    const productCombine = productFilter.combine || {};
    const defaultProduct = productFilter.default || "全部";
    const kpiConfig = config.kpiConfig || {};
    const chartState = {};
    const state = {
      preset: config.defaultRange || "30D",
      product: defaultProduct,
      ...computeRange(config.defaultRange || "30D", allDates),
    };

    function matchesProduct(row) {
      if (!productField || state.product === "全部") return true;
      const value = String(row[productField] || "");
      if (productCombine[state.product]) {
        return productCombine[state.product].includes(value);
      }
      return value === state.product;
    }

    function filteredRows(key) {
      const rows = (config.datasets && config.datasets[key]) || [];
      return rows.filter((row) => withinRange(row, state) && matchesProduct(row));
    }

    function aggregate() {
      const all = filteredRows("allRows");
      const paid = filteredRows("paidRows");

      const accounts = {};
      all.forEach((r) => {
        const name = r["账号"] || "未知";
        accounts[name] = accounts[name] || { 笔记数: 0, 有成交: 0, 总曝光量: 0, 总阅读量: 0, 总互动量: 0, 总支付金额: 0, 总支付订单: 0, 总GPM: 0 };
        const a = accounts[name];
        a["笔记数"] += 1;
        a["总曝光量"] += r["曝光量"] || 0;
        a["总阅读量"] += r["阅读量"] || 0;
        a["总互动量"] += r["互动量"] || 0;
        if ((r["支付金额"] || 0) > 0) {
          a["有成交"] += 1;
          a["总支付金额"] += r["支付金额"];
          a["总支付订单"] += r["支付订单数"] || 0;
          a["总GPM"] += r["GPM"] || 0;
        }
      });
      const accountSummary = Object.entries(accounts)
        .map(([name, v]) => ({
          账号: name,
          笔记数: v["笔记数"],
          有成交: v["有成交"],
          总曝光量: v["总曝光量"],
          总阅读量: v["总阅读量"],
          总互动量: v["总互动量"],
          总支付金额: Math.round(v["总支付金额"] * 100) / 100,
          总支付订单: v["总支付订单"],
          成交率: v["笔记数"] ? `${(v["有成交"] / v["笔记数"] * 100).toFixed(1)}%` : "0%",
          平均GPM: v["有成交"] ? Math.round(v["总GPM"] / v["有成交"] * 100) / 100 : 0,
        }))
        .sort((a, b) => b["总支付金额"] - a["总支付金额"]);

      const promos = {};
      all.forEach((r) => {
        const p = r["推广状态"] || "未知";
        promos[p] = promos[p] || { 笔记数: 0, 总曝光量: 0, 总支付金额: 0, 总支付订单: 0, 有支付: 0, 总GPM: 0 };
        const v = promos[p];
        v["笔记数"] += 1;
        v["总曝光量"] += r["曝光量"] || 0;
        if ((r["支付金额"] || 0) > 0) {
          v["总支付金额"] += r["支付金额"];
          v["总支付订单"] += r["支付订单数"] || 0;
          v["有支付"] += 1;
          v["总GPM"] += r["GPM"] || 0;
        }
      });
      const promoSummary = Object.entries(promos)
        .map(([name, v]) => ({
          推广状态: name,
          笔记数: v["笔记数"],
          总曝光量: v["总曝光量"],
          总支付金额: Math.round(v["总支付金额"] * 100) / 100,
          总支付订单: v["总支付订单"],
          有支付: v["有支付"],
          平均GPM: v["有支付"] ? Math.round(v["总GPM"] / v["有支付"] * 100) / 100 : 0,
        }))
        .sort((a, b) => b["总支付金额"] - a["总支付金额"]);

      const types = {};
      all.forEach((r) => {
        const t = r["笔记类型"] || "未知";
        types[t] = types[t] || { 笔记数: 0, 总曝光量: 0, 总支付金额: 0, 有支付: 0, 总GPM: 0 };
        const v = types[t];
        v["笔记数"] += 1;
        v["总曝光量"] += r["曝光量"] || 0;
        if ((r["支付金额"] || 0) > 0) {
          v["总支付金额"] += r["支付金额"];
          v["有支付"] += 1;
          v["总GPM"] += r["GPM"] || 0;
        }
      });
      const typeSummary = Object.entries(types)
        .map(([name, v]) => ({
          笔记类型: name,
          笔记数: v["笔记数"],
          总曝光量: v["总曝光量"],
          总支付金额: Math.round(v["总支付金额"] * 100) / 100,
          有支付: v["有支付"],
          平均GPM: v["有支付"] ? Math.round(v["总GPM"] / v["有支付"] * 100) / 100 : 0,
        }))
        .sort((a, b) => b["总支付金额"] - a["总支付金额"]);

      const daily = {};
      paid.forEach((r) => {
        const d = r["date"];
        daily[d] = daily[d] || { 支付金额: 0, 支付订单: 0, 曝光量: 0, 互动量: 0 };
        const v = daily[d];
        v["支付金额"] += r["支付金额"];
        v["支付订单"] += r["支付订单数"] || 0;
        v["曝光量"] += r["曝光量"] || 0;
        v["互动量"] += r["互动量"] || 0;
      });
      const dailyTrend = Object.entries(daily)
        .sort((a, b) => (a[0] < b[0] ? -1 : 1))
        .map(([d, v]) => ({
          date: d,
          支付金额: Math.round(v["支付金额"] * 100) / 100,
          支付订单: v["支付订单"],
          曝光量: v["曝光量"],
          GPM: v["曝光量"] ? Math.round(v["支付金额"] / v["曝光量"] * 1000 * 100) / 100 : 0,
        }));

      // 商品维度汇总（支持商品筛选联动）
      const products = {};
      all.forEach((r) => {
        const pid = r["商品ID"] || "未知";
        const pname = r["商品名称"] || pid;
        if (!products[pid]) {
          products[pid] = { 商品ID: pid, 商品名称: pname, 笔记数: 0, 有成交: 0, 总曝光量: 0, 总阅读量: 0, 总支付金额: 0, 总支付订单: 0, 总商品点击: 0 };
        }
        const p = products[pid];
        p["笔记数"] += 1;
        p["总曝光量"] += r["曝光量"] || 0;
        p["总阅读量"] += r["阅读量"] || 0;
        p["总商品点击"] += r["商品点击次数"] || 0;
        if ((r["支付金额"] || 0) > 0) {
          p["有成交"] += 1;
          p["总支付金额"] += r["支付金额"];
          p["总支付订单"] += r["支付订单数"] || 0;
        }
      });
      const productSummary = Object.values(products)
        .map((p) => ({
          商品ID: p["商品ID"],
          商品名称: p["商品名称"],
          笔记数: p["笔记数"],
          有成交: p["有成交"],
          总曝光量: p["总曝光量"],
          总阅读量: p["总阅读量"],
          总支付金额: Math.round(p["总支付金额"] * 100) / 100,
          总支付订单: p["总支付订单"],
          平均GPM: p["总曝光量"] ? Math.round(p["总支付金额"] / p["总曝光量"] * 1000 * 100) / 100 : 0,
          平均CTR: p["总曝光量"] ? Math.round(p["总阅读量"] / p["总曝光量"] * 10000) / 100 : 0,
          平均CVR: p["总商品点击"] ? Math.round(p["总支付订单"] / p["总商品点击"] * 10000) / 100 : 0,
        }))
        .sort((a, b) => b["总支付金额"] - a["总支付金额"]);

      // ===== 转化漏斗 =====
      const totalExp = all.reduce((s, r) => s + (r["曝光量"] || 0), 0);
      const totalRead = all.reduce((s, r) => s + (r["阅读量"] || 0), 0);
      const totalClicks = all.reduce((s, r) => s + (r["商品点击次数"] || 0), 0);
      const totalOrders = paid.reduce((s, r) => s + (r["支付订单数"] || 0), 0);
      const totalPay = paid.reduce((s, r) => s + (r["支付金额"] || 0), 0);
      const funnel = [
        { 环节: "曝光量", 数值: totalExp, 转化率: 100, 价值: totalPay },
        { 环节: "阅读量", 数值: totalRead, 转化率: totalExp ? totalRead / totalExp * 100 : 0, 价值: totalPay },
        { 环节: "商品点击", 数值: totalClicks, 转化率: totalRead ? totalClicks / totalRead * 100 : 0, 价值: totalPay },
        { 环节: "支付订单", 数值: totalOrders, 转化率: totalClicks ? totalOrders / totalClicks * 100 : 0, 价值: totalPay },
      ];

      // ===== 三层分级（按支付金额排序）=====
      const paidSorted = paid.slice().sort((a, b) => (b["支付金额"] || 0) - (a["支付金额"] || 0));
      const top10 = paidSorted.slice(0, 10);
      const top11_50 = paidSorted.slice(10, 50);
      const longTail = paidSorted.slice(50);
      const top10Pay = top10.reduce((s, r) => s + (r["支付金额"] || 0), 0);
      const top11_50Pay = top11_50.reduce((s, r) => s + (r["支付金额"] || 0), 0);
      const longTailPay = longTail.reduce((s, r) => s + (r["支付金额"] || 0), 0);
      const threeTier = [
        { 层级: "🔥 爆款层 (TOP10)", 笔记数: top10.length, 支付金额: top10Pay, 占比: totalPay ? top10Pay / totalPay * 100 : 0, 笔记: top10 },
        { 层级: "⭐ 潜力层 (11-50名)", 笔记数: top11_50.length, 支付金额: top11_50Pay, 占比: totalPay ? top11_50Pay / totalPay * 100 : 0, 笔记: top11_50 },
        { 层级: "📉 长尾层 (50名以后)", 笔记数: longTail.length, 支付金额: longTailPay, 占比: totalPay ? longTailPay / totalPay * 100 : 0, 笔记: longTail },
      ];

      // ===== 零成交笔记分析 =====
      const zeroPay = all.filter(r => (r["支付金额"] || 0) === 0);
      // 按CTR和商品点击率分四象限
      const zeroWithData = zeroPay.filter(r => r["曝光量"] > 0);
      const ctrs = zeroWithData.map(r => (r["阅读量"] || 0) / r["曝光量"]).sort((a, b) => a - b);
      const clickRates = zeroWithData.map(r => (r["商品点击次数"] || 0) / Math.max(r["阅读量"] || 1, 1)).sort((a, b) => a - b);
      const medCtrZero = ctrs[Math.floor(ctrs.length / 2)] || 0;
      const medClickZero = clickRates[Math.floor(clickRates.length / 2)] || 0;
      const zeroQuadrants = { q1: [], q2: [], q3: [], q4: [] };
      zeroWithData.forEach(r => {
        const ctr = (r["阅读量"] || 0) / (r["曝光量"] || 1);
        const clickRate = (r["商品点击次数"] || 0) / Math.max(r["阅读量"] || 1, 1);
        const hiCtr = ctr >= medCtrZero;
        const hiClick = clickRate >= medClickZero;
        const key = hiCtr ? (hiClick ? "q1" : "q4") : (hiClick ? "q2" : "q3");
        zeroQuadrants[key].push({ ...r, CTR: ctr * 100, 商品点击率: clickRate * 100 });
      });
      const zeroAnalysis = {
        总数: zeroPay.length,
        占比: all.length ? zeroPay.length / all.length * 100 : 0,
        总曝光: zeroPay.reduce((s, r) => s + (r["曝光量"] || 0), 0),
        四象限: zeroQuadrants,
        中位数CTR: medCtrZero * 100,
        中位数商品点击率: medClickZero * 100,
      };

      // ===== 功能1: 笔记生命周期分析 =====
      const lifecycleSummary = [];
      const ageGroups = [
        { name: "0-3天", maxDays: 3 },
        { name: "3-7天", minDays: 3, maxDays: 7 },
        { name: "7-30天", minDays: 7, maxDays: 30 },
        { name: "30-90天", minDays: 30, maxDays: 90 },
        { name: "90天+", minDays: 90 }
      ];
      
      const dateValues = all.map(r => parseDate(r.date)).filter(d => d);
      const latestDate = dateValues.length ? new Date(Math.max(...dateValues)) : new Date();
      
      ageGroups.forEach(group => {
        const filtered = all.filter(r => {
          const d = parseDate(r.date);
          if (!d) return false;
          const daysAgo = (latestDate - d) / (1000 * 60 * 60 * 24);
          return (group.minDays === undefined || daysAgo > group.minDays) && 
                 (group.maxDays === undefined || daysAgo <= group.maxDays);
        });
        
        const paidInGroup = filtered.filter(r => (r["支付金额"] || 0) > 0);
        const totalExp = filtered.reduce((s, r) => s + (r["曝光量"] || 0), 0);
        const totalRead = filtered.reduce((s, r) => s + (r["阅读量"] || 0), 0);
        const totalClicks = filtered.reduce((s, r) => s + (r["商品点击次数"] || 0), 0);
        const totalOrders = paidInGroup.reduce((s, r) => s + (r["支付订单数"] || 0), 0);
        const totalPay = paidInGroup.reduce((s, r) => s + (r["支付金额"] || 0), 0);
        
        lifecycleSummary.push({
          "年龄段": group.name,
          "笔记数": filtered.length,
          "有成交": paidInGroup.length,
          "总曝光量": totalExp,
          "总阅读量": totalRead,
          "总商品点击": totalClicks,
          "总支付金额": Math.round(totalPay * 100) / 100,
          "总支付订单": totalOrders,
          "平均GPM": totalExp ? Math.round(totalPay / totalExp * 1000 * 100) / 100 : 0,
          "平均CTR": totalExp ? Math.round(totalRead / totalExp * 10000) / 100 : 0,
          "平均CVR": totalClicks ? Math.round(totalOrders / totalClicks * 10000) / 100 : 0,
          "成交率": filtered.length ? Math.round(paidInGroup.length / filtered.length * 1000) / 10 : 0
        });
      });

      // ===== 功能2: 基准对比分析 =====
      const CTR_LOW = 5.80;
      const CTR_HIGH = 7.84;
      const CVR_LOW = 6.54;
      const CVR_HIGH = 8.84;
      
      function getBenchmarkLevel(value, low, high) {
        if (value < low) return { level: "低于大盘", color: "#ef4444" };
        if (value > high) return { level: "优于大盘", color: "#22c55e" };
        return { level: "近似大盘", color: "#f59e0b" };
      }
      
      const overallCTR = totalExp ? Math.round(totalRead / totalExp * 10000) / 100 : 0;
      const overallCVR = totalClicks ? Math.round(totalOrders / totalClicks * 10000) / 100 : 0;
      
      const benchmarkData = {
        CTR: {
          value: overallCTR,
          low: CTR_LOW,
          high: CTR_HIGH,
          ...getBenchmarkLevel(overallCTR, CTR_LOW, CTR_HIGH)
        },
        CVR: {
          value: overallCVR,
          low: CVR_LOW,
          high: CVR_HIGH,
          ...getBenchmarkLevel(overallCVR, CVR_LOW, CVR_HIGH)
        },
        reference: {
          CTR: "商笔CTR参考区间: 5.80%~7.84%",
          CVR: "商笔商品转化率参考区间: 6.54%~8.84%"
        }
      };
      
      // 每条笔记的基准分类
      const benchmarkDistribution = {
        CTR: { "低于大盘": 0, "近似大盘": 0, "优于大盘": 0 },
        CVR: { "低于大盘": 0, "近似大盘": 0, "优于大盘": 0 }
      };
      
      all.forEach(r => {
        const exp = r["曝光量"] || 0;
        const read = r["阅读量"] || 0;
        const clicks = r["商品点击次数"] || 0;
        const orders = r["支付订单数"] || 0;
        
        if (exp > 0) {
          const noteCTR = read / exp * 100;
          const ctrLevel = getBenchmarkLevel(noteCTR, CTR_LOW, CTR_HIGH);
          benchmarkDistribution.CTR[ctrLevel.level]++;
        }
        if (clicks > 0) {
          const noteCVR = orders / clicks * 100;
          const cvrLevel = getBenchmarkLevel(noteCVR, CVR_LOW, CVR_HIGH);
          benchmarkDistribution.CVR[cvrLevel.level]++;
        }
      });

      // ===== 功能3: 商品维度深度分析 =====
      // 3.1 各商品转化漏斗对比
      const productFunnels = productSummary.map(p => ({
        商品名称: p["商品名称"].length > 8 ? p["商品名称"].slice(0, 8) + "..." : p["商品名称"],
        商品ID: p["商品ID"],
        曝光量: p["总曝光量"],
        阅读量: p["总阅读量"],
        商品点击: p["总商品点击"] || 0,
        支付订单: p["总支付订单"],
        支付金额: p["总支付金额"],
        CTR: p["平均CTR"],
        CVR: p["平均CVR"],
        GPM: p["平均GPM"]
      }));
      
      // 3.2 账号-商品矩阵热力图数据
      const accountProductMatrix = [];
      const accountSet = new Set();
      const productSet = new Set();
      const apData = {};
      
      all.forEach(r => {
        const acc = r["账号"] || "未知";
        const pid = r["商品ID"] || "未知";
        const pname = r["商品名称"] || pid;
        accountSet.add(acc);
        productSet.add(pname);
        const key = `${acc}__${pname}`;
        if (!apData[key]) {
          apData[key] = { 账号: acc, 商品: pname, 笔记数: 0, 支付金额: 0, GPM: 0, 曝光量: 0 };
        }
        apData[key].笔记数 += 1;
        apData[key].曝光量 += r["曝光量"] || 0;
        if ((r["支付金额"] || 0) > 0) {
          apData[key].支付金额 += r["支付金额"];
          apData[key].GPM += r["GPM"] || 0;
        }
      });
      
      const accountList = Array.from(accountSet);
      const productList = Array.from(productSet);
      
      Object.values(apData).forEach(d => {
        const avgGPM = d.笔记数 && d.曝光量 ? d.支付金额 / d.曝光量 * 1000 : 0;
        accountProductMatrix.push([
          accountList.indexOf(d.账号),
          productList.indexOf(d.商品),
          Math.round(avgGPM * 100) / 100
        ]);
      });
      
      // 3.3 效率-规模错位分析（GPM vs 曝光量散点，商品维度）
      const efficiencyScale = productSummary.map(p => ({
        商品名称: p["商品名称"],
        商品ID: p["商品ID"],
        总曝光量: p["总曝光量"],
        平均GPM: p["平均GPM"],
        总支付金额: p["总支付金额"],
        笔记数: p["笔记数"]
      }));
      
      const productDepthAnalysis = {
        productFunnels,
        accountProductMatrix,
        accountList,
        productList,
        efficiencyScale
      };

      return { accountSummary, promoSummary, typeSummary, dailyTrend, productSummary, funnel, threeTier, zeroAnalysis, lifecycleSummary, benchmarkData, benchmarkDistribution, productDepthAnalysis };
    }

    function setRangeLabel() {
      const label = document.getElementById("activeRangeLabel");
      if (!label) return;
      const productNames = productFilter.productNames || {};
      const scope = state.product === "全部" ? "全部商品" : productNames[state.product] || state.product;
      label.textContent = state.start && state.end ? `${scope} · ${state.start} to ${state.end}` : `${scope} · No dated rows`;
    }

    function setDateInputs() {
      const start = document.getElementById("rangeStart");
      const end = document.getElementById("rangeEnd");
      if (start) start.value = state.start || "";
      if (end) end.value = state.end || "";
    }

    function setActivePreset() {
      document.querySelectorAll("[data-range-preset]").forEach((button) => {
        button.classList.toggle("active", button.dataset.rangePreset === state.preset);
      });
    }

    function setActiveProduct() {
      const select = document.getElementById("productSelect");
      if (select) select.value = state.product;
    }

    function updateKpis() {
      Object.entries(kpiConfig).forEach(([id, kpi]) => {
        const tile = document.getElementById(id);
        if (!tile) return;
        const rows = filteredRows("allRows");
        const paid = filteredRows("paidRows");
        const labelEl = tile.querySelector("p");
        const valueEl = tile.querySelector("strong");
        const deltaEl = tile.querySelector("span");
        const detailEl = tile.querySelector("small");
        if (labelEl && kpi.label) labelEl.textContent = kpi.label;
        if (valueEl) valueEl.textContent = kpi.value(rows, paid);
        if (deltaEl) deltaEl.textContent = kpi.delta(rows, paid);
        if (detailEl) detailEl.textContent = kpi.detail(rows, paid);
      });
    }

    function initChart(id, type) {
      const el = document.getElementById(id);
      if (!el || !chartFactories[id]) return;
      const chart = echarts.init(el, null, { renderer: "canvas" });
      chartState[id] = { chart, type };
      chart.setOption(chartFactories[id](type, filteredRows, aggregate), true);
    }

    function updateCharts() {
      Object.entries(chartState).forEach(([id, entry]) => {
        if (chartFactories[id]) entry.chart.setOption(chartFactories[id](entry.type, filteredRows, aggregate), true);
      });
    }

    function updateTables() {
      Object.entries(tables).forEach(([id, tableConfig]) => {
        const body = document.querySelector(`#${id} tbody`);
        if (!body) return;

        // 商品效率榜单使用 aggregate 数据（支持筛选联动）
        let rows;
        if (tableConfig.useAggregate === "productSummary") {
          rows = (aggregate().productSummary || []).slice();
        } else {
          rows = filteredRows(tableConfig.dataset).slice();
        }

        // 四象限榜单特殊处理：计算象限并按优先级排序
        if (tableConfig.isQuadrantRank && rows.length > 0) {
          const exps = rows.map(r => r["曝光量"] || 0).sort((a, b) => a - b);
          const gpms = rows.map(r => r["GPM"] || 0).sort((a, b) => a - b);
          const medExp = exps[Math.floor(exps.length / 2)];
          const medGpm = gpms[Math.floor(gpms.length / 2)];

          const quadrantOrder = { "优质素材": 1, "潜力素材": 2, "需改进": 3, "待优化": 4 };

          rows = rows.map(r => {
            const hiExp = (r["曝光量"] || 0) >= medExp;
            const hiGpm = (r["GPM"] || 0) >= medGpm;
            let quadrant = "待优化";
            if (hiExp && hiGpm) quadrant = "优质素材";
            else if (!hiExp && hiGpm) quadrant = "潜力素材";
            else if (hiExp && !hiGpm) quadrant = "需改进";
            return { ...r, "象限": quadrant };
          });

          rows.sort((a, b) => {
            const qa = quadrantOrder[a["象限"]] || 99;
            const qb = quadrantOrder[b["象限"]] || 99;
            if (qa !== qb) return qa - qb;
            const pa = a["支付金额"] || 0;
            const pb = b["支付金额"] || 0;
            return pb - pa;
          });
        } else if (tableConfig.sortField) {
          rows.sort((a, b) => {
            const left = a[tableConfig.sortField];
            const right = b[tableConfig.sortField];
            if (typeof left === "number" && typeof right === "number") {
              return tableConfig.sortDirection === "asc" ? left - right : right - left;
            }
            return tableConfig.sortDirection === "asc"
              ? String(left).localeCompare(String(right))
              : String(right).localeCompare(String(left));
          });
        }
        const limited = rows.slice(0, tableConfig.limit || 12);
        body.replaceChildren(
          ...limited.map((row) => {
            const tr = document.createElement("tr");
            tableConfig.columns.forEach((column) => {
              const td = document.createElement("td");
              td.textContent = row[column.field] == null ? "" : String(row[column.field]);
              if (column.numeric) td.className = "num";
              tr.appendChild(td);
            });
            return tr;
          })
        );
      });
    }

    function refresh() {
      setRangeLabel();
      setDateInputs();
      setActivePreset();
      setActiveProduct();
      updateKpis();
      updateCharts();
      updateTables();
    }

    window.setDashboardRange = function setDashboardRange(preset) {
      state.preset = preset;
      const next = computeRange(preset, allDates);
      state.start = next.start;
      state.end = next.end;
      refresh();
    };

    window.setCustomDashboardRange = function setCustomDashboardRange() {
      const start = document.getElementById("rangeStart");
      const end = document.getElementById("rangeEnd");
      state.preset = "CUSTOM";
      state.start = start ? start.value : "";
      state.end = end ? end.value : "";
      refresh();
    };

    window.setProductFilter = function setProductFilter(value) {
      if (productOptions.length && !productOptions.includes(value)) return;
      state.product = value;
      refresh();
    };

    window.setChartType = function setChartType(id, type) {
      if (!chartState[id] || !chartFactories[id]) return;
      chartState[id].type = type;
      chartState[id].chart.setOption(chartFactories[id](type, filteredRows, aggregate), true);
    };

    window.toggleMenu = function toggleMenu(id) {
      document.querySelectorAll(".menu").forEach((menu) => {
        if (menu.id !== `menu-${id}`) menu.classList.remove("open");
      });
      const menu = document.getElementById(`menu-${id}`);
      if (menu) menu.classList.toggle("open");
    };

    window.toggleEdit = function toggleEdit(id) {
      const menu = document.getElementById(`menu-${id}`);
      const panel = document.getElementById(`edit-${id}`);
      if (menu) menu.classList.remove("open");
      if (panel) panel.classList.toggle("open");
    };

    window.viewSource = function viewSource(id) {
      const menu = document.getElementById(`menu-${id}`);
      if (menu) menu.classList.remove("open");
      document.getElementById("modalTitle").textContent = "Data Source";
      document.getElementById("modalSubtitle").textContent =
        (config.modalSubtitlePrefix || "Dashboard transform for ") + id + ".";
      document.getElementById("modalSnippet").textContent = sourceMap[id] || "";
      document.getElementById("modalCode").textContent = config.fullScript || "";
      document.getElementById("modalBackdrop").classList.add("open");
    };

    window.closeModal = function closeModal() {
      document.getElementById("modalBackdrop").classList.remove("open");
    };

    window.copyCode = async function copyCode(codeId, button) {
      const text = document.getElementById(codeId).textContent || "";
      try {
        await navigator.clipboard.writeText(text);
      } catch (err) {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }
      const previousLabel = button.getAttribute("aria-label") || "Copy";
      button.classList.add("copied");
      button.setAttribute("aria-label", "Copied");
      button.setAttribute("title", "Copied");
      setTimeout(() => {
        button.classList.remove("copied");
        button.setAttribute("aria-label", previousLabel);
        button.removeAttribute("title");
      }, 1200);
    };

    (config.initialCharts || []).forEach((item) => initChart(item.id, item.type));
    refresh();

    document.querySelectorAll("[data-range-preset]").forEach((button) => {
      button.addEventListener("click", () => window.setDashboardRange(button.dataset.rangePreset));
    });
    document.querySelectorAll("[data-range-input]").forEach((input) => {
      input.addEventListener("change", window.setCustomDashboardRange);
    });
    const productSelect = document.getElementById("productSelect");
    if (productSelect) {
      productSelect.addEventListener("change", (e) => window.setProductFilter(e.target.value));
    }
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".toolbox")) {
        document.querySelectorAll(".menu").forEach((menu) => menu.classList.remove("open"));
      }
    });
    window.addEventListener("resize", () => {
      Object.values(chartState).forEach((entry) => entry.chart.resize());
    });
  };
})();
