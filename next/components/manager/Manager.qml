import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Polaris.Ui 1.0 as Ui

Item {
    id: root; objectName: 'extensionManagementPage'
    property var manager: null
    property var applicationHost: null
    required property QtObject theme
    signal openApplication(string identity)
    signal openComponentView(string identity)
    signal holdChanged(string reason, bool active)
    property string category: 'applications'
    property string selectedApplicationId: ''
    property string selectedId: ''
    property bool showSystemComponents: false
    property bool technicalDetails: false
    onSelectedIdChanged: technicalDetails = false
    readonly property var records: JSON.parse(manager ? manager.dataJson : '[]')
    readonly property var applications: JSON.parse(applicationHost ? applicationHost.managedApplicationsJson : '[]')
    readonly property var currentApplication: applications.find(function(row) { return row.applicationId === selectedApplicationId }) || applications[0] || ({})
    readonly property var packages: records.filter(function(row) { return row.isDefault !== false && row.manifest.kind !== 'application' && (showSystemComponents || ['authorization','collaboration','runtime','window','canvas','pet','manager','sources'].indexOf(row.id) < 0) })
    readonly property var current: records.find(function(row) { return row.id === selectedId }) || packages[0] || ({})
    readonly property var currentPackage: packages.find(function(row) { return row.componentType === current.componentType }) || ({})
    readonly property var instances: records.filter(function(row) { return row.componentType === current.componentType && row.manifest.kind !== 'application' })
    readonly property var packageChoices: packages.map(function(row) { return Object.assign({}, row, {title:row.manifest.name}) })
    readonly property var sources: JSON.parse(manager ? manager.sourcesJson : '[]')
    property string marketKind: 'all'
    property string marketSource: ''
    property string marketQuery: ''
    property string marketTag: ''
    property string marketAuthor: ''
    property bool marketSourceInitialized: false
    property bool showMarketFilters: false
    property bool showArchivedSources: false
    readonly property var activeSources: sources.filter(function(source) { return !source.archived })
    readonly property var archivedSources: sources.filter(function(source) { return !!source.archived })
    onSourcesChanged: {
        var preferred = sources.find(function(source) { return source.defaultCatalog && !source.archived });
        if ((!marketSourceInitialized || (marketSource && !sources.some(function(source) { return source.id === marketSource && !source.archived }))) && preferred) {
            marketSource = preferred.id; marketSourceInitialized = true;
        } else if (marketSource && !sources.some(function(source) { return source.id === marketSource && !source.archived })) {
            marketSource = '';
        }
    }
    readonly property var sourceChoices: [{id:'',name:'全部来源'}].concat(activeSources.map(function(row) { return {id:row.id,name:row.name || row.location} }))
    readonly property var filteredSources: activeSources.filter(function(source) { return !marketSource || source.id === marketSource })
    readonly property var allMarketEntries: {
        var entries = [];
        activeSources.forEach(function(source) {
            var rows = source.packages || (source.components || []).map(function(entry) { return Object.assign({type:'component'}, entry) }).concat((source.applications || []).map(function(entry) { return Object.assign({type:'application'}, entry) }));
            rows.forEach(function(entry) {
                var normalizedName = manager.normalizeMarketText(entry.manifest.name);
                var searchText = [entry.manifest.name, entry.manifest.id, entry.summary || '', entry.description || '', entry.author || ''].concat(entry.tags || []).join(' ');
                entries.push(Object.assign({}, entry, {kind:entry.type,sourceId:source.id,sourceName:source.name || source.location,revision:source.revision,
                    iconUrl:entry.icon ? manager.marketAssetUrl(source.directory, entry.icon) : '', sourceDirectory:source.directory,
                    searchName:normalizedName, searchId:manager.normalizeMarketText(entry.manifest.id), searchText:manager.normalizeMarketText(searchText), order:entries.length}));
            });
        });
        return entries;
    }
    readonly property var marketTags: {
        var tags = [];
        allMarketEntries.forEach(function(entry) { (entry.tags || []).forEach(function(tag) { if (tags.indexOf(tag) < 0) tags.push(tag) }) });
        return ['全部标签'].concat(tags.sort());
    }
    readonly property var marketAuthors: {
        var authors = [];
        allMarketEntries.forEach(function(entry) { if (entry.author && authors.indexOf(entry.author) < 0) authors.push(entry.author) });
        return ['全部作者'].concat(authors.sort());
    }
    readonly property var marketEntries: {
        var query = manager ? manager.normalizeMarketText(marketQuery).trim() : '';
        var words = query ? query.split(/\s+/) : [];
        return allMarketEntries.filter(function(entry) {
            return (!marketSource || entry.sourceId === marketSource) && (marketKind === 'all' || entry.kind === marketKind)
                && (!marketTag || (entry.tags || []).indexOf(marketTag) >= 0) && (!marketAuthor || entry.author === marketAuthor)
                && words.every(function(word) { return entry.searchText.indexOf(word) >= 0 });
        }).sort(function(a, b) {
            function rank(entry) { return !query ? 0 : entry.searchName === query || entry.searchId === query ? 0 : entry.searchName.indexOf(query) === 0 || entry.searchId.indexOf(query) === 0 ? 1 : 2 }
            return rank(a) - rank(b) || (a.searchName < b.searchName ? -1 : a.searchName > b.searchName ? 1 : 0) || (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0) || (a.searchId < b.searchId ? -1 : a.searchId > b.searchId ? 1 : 0) || (a.sourceId < b.sourceId ? -1 : a.sourceId > b.sourceId ? 1 : 0);
        });
    }
    function matchingApplications(entry) { return applications.filter(function(app) { return app.packageId === entry.manifest.id }) }
    function marketActionText(entry) {
        if (entry.kind === 'application') {
            var matches = matchingApplications(entry);
            if (!matches.length) return '安装';
            if (matches.length === 1 && matches[0].package && matches[0].package.digest === entry.contentDigest) return '已安装';
            if (matches.length === 1 && matches[0].origin && matches[0].origin.sourceId === entry.sourceId) return '更新';
            return matches.length === 1 ? '从此源更新' : '选择应用更新…';
        }
        if (!records.some(function(row) { return row.id === entry.manifest.id })) return '安装';
        var origin = entry.installationOrigin;
        if (origin && origin.contentDigest === entry.contentDigest) return '已安装';
        return origin && origin.sourceId === entry.sourceId ? '更新' : '从此源替换';
    }
    function marketOtherSource(entry) {
        if (marketActionText(entry) !== '已安装') return false;
        if (entry.kind === 'application') {
            var matches = matchingApplications(entry);
            return matches.length === 1 && (!matches[0].origin || matches[0].origin.sourceId !== entry.sourceId);
        }
        return entry.installationOrigin && entry.installationOrigin.sourceId !== entry.sourceId;
    }
    function marketInstalledOrigin(entry) {
        if (!marketOtherSource(entry)) return '';
        var origin = entry.kind === 'application' ? matchingApplications(entry)[0].origin : entry.installationOrigin;
        if (!origin) return '已安装 · 本地';
        var source = sources.find(function(row) { return row.id === origin.sourceId });
        return '已安装 · ' + (source ? (source.name || source.location) : '其他来源');
    }
    function removableComponent(entry) {
        return records.find(function(row) { return row.id === entry.manifest.id && row.isDefault !== false && row.manageable }) || null;
    }
    function removeMarketEntry(entry) {
        if (entry.kind === 'component') { manager.prepareUninstall(entry.manifest.id); return; }
        var matches = matchingApplications(entry).filter(function(app) { return !app.builtin });
        if (matches.length === 1) {
            removeApplicationDialog.applicationId = matches[0].applicationId;
            removeApplicationDialog.applicationTitle = matches[0].title;
            removeApplicationDialog.open();
        } else if (matches.length > 1) {
            sourceApplicationRemoval.targets = matches.map(function(app) { return {applicationId:app.applicationId,title:app.title + ' · ' + app.applicationId.slice(0,8)} });
            removalTarget.currentIndex = -1;
            sourceApplicationRemoval.open();
        }
    }
    function installMarketEntry(entry) {
        manager.dismissNotice();
        if (entry.kind === 'component') { manager.installSource(entry.sourceId, entry.manifest.id, entry.revision); return; }
        var matches = matchingApplications(entry);
        if (!matches.length) {
            var identity = applicationHost.installSourceApplication(entry.sourceId, entry.manifest.id, entry.revision);
            if (identity) selectedApplicationId = identity;
        } else if (matches.length === 1) {
            applicationHost.updateSourceApplication(matches[0].applicationId, entry.sourceId, entry.manifest.id, entry.revision);
        } else {
            sourceApplicationUpdate.entry = entry;
            sourceApplicationUpdate.targets = matches.map(function(app) { return {applicationId:app.applicationId,title:app.title + ' · ' + app.applicationId.slice(0,8)} });
            sourceApplicationTarget.currentIndex = -1;
            sourceApplicationUpdate.open();
        }
    }
    onVisibleChanged: { if (visible && applicationHost) applicationHost.refreshManagedApplications(); if (visible && category === 'market' && manager) manager.refresh(); }
    onCategoryChanged: { if ((category === 'applications' || category === 'market') && applicationHost) applicationHost.refreshManagedApplications(); if (visible && category === 'market' && manager) manager.refresh(); }
    function stateText(state) { return ({installed:'已安装',starting:'启动中',running:'运行中',stopping:'停止中',stopped:'已停止',failed:'异常'})[state] || state || '' }
    Connections { target: root.manager; function onInstanceCreated(identity) { root.selectedId = identity } }
    readonly property bool wideDetails: width >= 640
    ColumnLayout {
        anchors.fill: parent; spacing: 14
        Flow {
            Layout.fillWidth: true; spacing: 8
            Ui.Button { theme: root.theme; objectName: 'extensionsMarketTab'; text: '市场'; primary: root.category === 'market'; onClicked: root.category = 'market' }
            Ui.Button { theme: root.theme; objectName: 'extensionsApplicationsTab'; text: '应用'; primary: root.category === 'applications'; onClicked: root.category = 'applications' }
            Ui.Button { theme: root.theme; objectName: 'extensionsComponentsTab'; text: '组件'; primary: root.category === 'components'; onClicked: root.category = 'components' }
        }
        ColumnLayout {
            visible: root.category === 'applications'; enabled: visible; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
            Text { Layout.fillWidth: true; text: '安装和管理应用，打开应用后连接所需组件实例。'; color: root.theme.muted; wrapMode: Text.Wrap; font.pixelSize: 13 }
            Flow { Layout.fillWidth: true; spacing: 8
                Ui.Button { theme: root.theme; text: '从目录安装'; glyph: 'plus'; objectName: 'installApplication'; onClicked: installApplicationFolder.open() }
                Ui.Button { theme: root.theme; text: '刷新'; onClicked: root.applicationHost.refreshManagedApplications() }
            }
            Ui.ComboBox { theme: root.theme; objectName: 'applicationsCompactSelector'; visible: !root.wideDetails; Layout.fillWidth: true; model: root.applications; textRole: 'title'; currentIndex: root.applications.findIndex(function(row) { return row.applicationId === root.currentApplication.applicationId }); onActivated: function(index) { root.selectedApplicationId = root.applications[index].applicationId } }
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 16
                ScrollView {
                    id: applicationsList; visible: root.wideDetails; Layout.preferredWidth: 180; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                    ScrollBar.vertical: Ui.ScrollBar { theme: root.theme }
                    ColumnLayout { width: applicationsList.availableWidth; spacing: 6
                        Repeater { model: root.applications
                            Ui.NavigationItem { required property var modelData; theme: root.theme; Layout.fillWidth: true; glyph: ''; text: modelData.title; selected: root.currentApplication.applicationId === modelData.applicationId; objectName: 'managedApplication_' + modelData.applicationId; onClicked: root.selectedApplicationId = modelData.applicationId }
                        }
                    }
                }
                ScrollView { id: appDetailScroll; objectName: 'appDetailScroll'; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                    ScrollBar.vertical: Ui.ScrollBar { theme: root.theme }
                    Rectangle {
                        visible: !!root.currentApplication.applicationId; width: appDetailScroll.availableWidth; implicitHeight: appDetail.implicitHeight + 32; radius: 10; color: root.theme.card; border.color: root.theme.border
                        ColumnLayout {
                            id: appDetail; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; spacing: 10
                            Text { Layout.fillWidth: true; text: root.currentApplication.title || ''; textFormat: Text.PlainText; color: root.theme.ink; wrapMode: Text.Wrap; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Text { Layout.fillWidth: true; text: root.currentApplication.builtin ? '随平台提供' : root.stateText(root.currentApplication.state) + (root.currentApplication.version ? ' · ' + root.currentApplication.version : ''); color: root.theme.muted; wrapMode: Text.Wrap; font.pixelSize: 12 }
                            Text { Layout.fillWidth: true; visible: !!root.currentApplication.packageError; text: root.currentApplication.packageError || ''; color: root.theme.error; wrapMode: Text.Wrap }
                            Flow {
                                Layout.fillWidth: true; spacing: 8
                                Ui.Button { theme: root.theme; text: '打开应用'; glyph: 'right'; objectName: 'openManagedApplication'; onClicked: root.openApplication(root.currentApplication.applicationId) }
                                Ui.Button { theme: root.theme; text: '更新应用'; objectName: 'updateManagedApplication'; visible: !root.currentApplication.builtin && !!root.currentApplication.package; onClicked: { updateApplicationFolder.applicationId = root.currentApplication.applicationId; updateApplicationFolder.open() } }
                                Ui.Button { theme: root.theme; text: '卸载应用'; objectName: 'removeManagedApplication'; visible: !root.currentApplication.builtin; onClicked: { removeApplicationDialog.applicationId = root.currentApplication.applicationId; removeApplicationDialog.applicationTitle = root.currentApplication.title; removeApplicationDialog.open() } }
                            }
                        }
                    }

                }
            }
        }
        ColumnLayout {
            visible: root.category === 'components'; enabled: visible; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
            Text { Layout.fillWidth: true; text: '组件安装在平台中，每个实例保存自己的配置和数据。'; color: root.theme.muted; wrapMode: Text.Wrap; font.pixelSize: 13 }
            Flow { Layout.fillWidth: true; spacing: 8
                Ui.Button { theme: root.theme; text: '从目录安装 / 替换'; objectName: 'installComponent'; onClicked: componentFolder.open() }
                Ui.Button { theme: root.theme; text: '刷新'; onClicked: if (root.manager) root.manager.refresh() }
                Ui.Button { theme: root.theme; text: root.showSystemComponents ? '收起系统组件' : '显示系统组件'; objectName: 'toggleSystemComponents'; onClicked: { root.showSystemComponents = !root.showSystemComponents; root.selectedId = '' } }
            }
            Ui.ComboBox { theme: root.theme; objectName: 'componentsCompactSelector'; visible: !root.wideDetails; Layout.fillWidth: true; model: root.packageChoices; textRole: 'title'; currentIndex: root.packageChoices.findIndex(function(row) { return row.componentType === root.current.componentType }); onActivated: function(index) { root.selectedId = root.packageChoices[index].id } }
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 16
                ScrollView {
                    id: componentsList; visible: root.wideDetails; Layout.preferredWidth: 180; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                    ScrollBar.vertical: Ui.ScrollBar { theme: root.theme }
                    ColumnLayout { width: componentsList.availableWidth; spacing: 6
                        Repeater { model: root.packageChoices
                            Ui.NavigationItem { required property var modelData; theme: root.theme; Layout.fillWidth: true; glyph: ''; text: modelData.title; selected: root.current.componentType === modelData.componentType; objectName: 'managedComponent_' + modelData.id; onClicked: root.selectedId = modelData.id }
                        }
                    }
                }
                ScrollView { id: componentDetailScroll; objectName: 'componentDetailScroll'; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                    ScrollBar.vertical: Ui.ScrollBar { theme: root.theme }
                    Rectangle {
                        width: componentDetailScroll.availableWidth; visible: !!root.current.id; implicitHeight: componentDetail.implicitHeight + 32; radius: 10; color: root.theme.card; border.color: root.theme.border
                        ColumnLayout {
                            id: componentDetail; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; spacing: 12
                            Text { Layout.fillWidth: true; text: root.currentPackage.manifest ? root.currentPackage.manifest.name : ''; color: root.theme.ink; font.pixelSize: 16; font.weight: Font.DemiBold; wrapMode: Text.Wrap }
                            Text { Layout.fillWidth: true; text: root.currentPackage.manifest ? '版本 ' + root.currentPackage.manifest.version : ''; color: root.theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                            Flow {
                                Layout.fillWidth: true; spacing: 8
                                Ui.Button { theme: root.theme; text: '新建实例'; objectName: 'createComponentInstance'; visible: !!root.currentPackage.canCreateInstance; enabled: root.manager && !root.manager.busy; onClicked: root.manager.createInstance(root.currentPackage.id) }
                                Ui.Button { theme: root.theme; text: '卸载组件'; objectName: 'uninstallComponent'; enabled: !!root.currentPackage.manageable && root.manager && !root.manager.busy; onClicked: root.manager.prepareUninstall(root.currentPackage.id) }
                            }
                            Text { text: '实例'; color: root.theme.ink; font.weight: Font.DemiBold; font.pixelSize: 14 }
                            Repeater {
                                model: root.instances
                                Ui.NavigationItem { required property var modelData; theme: root.theme; Layout.fillWidth: true; glyph: ''; text: (modelData.isDefault !== false ? '默认实例' : '实例 ' + modelData.instanceId.slice(0, 8)) + ' · ' + root.stateText(modelData.state); selected: root.current.id === modelData.id; objectName: 'managedInstance_' + modelData.id; onClicked: root.selectedId = modelData.id }
                            }
                            Ui.Button { theme: root.theme; text: root.technicalDetails ? '收起实例信息' : '实例信息'; onClicked: root.technicalDetails = !root.technicalDetails }
                            Text { visible: root.technicalDetails; Layout.fillWidth: true; text: root.current.instanceId || ''; color: root.theme.quiet; font.pixelSize: 11; wrapMode: Text.WrapAnywhere }
                            Text { Layout.fillWidth: true; visible: root.current.state === 'failed'; text: root.current.error ? (root.current.error.message || root.current.error) : ''; color: root.theme.error; wrapMode: Text.Wrap }
                            Flow {
                                Layout.fillWidth: true; spacing: 8
                                Ui.Button { theme: root.theme; text: '启动'; objectName: 'startComponentInstance'; enabled: root.manager && !root.manager.busy && ['installed','stopped','failed'].indexOf(root.current.state) >= 0; onClicked: root.manager.lifecycle(root.current.id, 'start') }
                                Ui.Button { theme: root.theme; text: '停止'; objectName: 'stopComponentInstance'; enabled: root.manager && !root.manager.busy && root.current.state === 'running'; onClicked: root.manager.lifecycle(root.current.id, 'stop') }
                                Ui.Button { theme: root.theme; text: '打开界面 / 配置'; objectName: 'configureComponentInstance'; enabled: root.current.state === 'running' && !!root.current.description && (root.current.description.views || []).some(function(view) { return view.adapter === 'qt-quick-item' || (view.actions || []).length > 0 }); onClicked: root.openComponentView(root.current.id) }
                                Ui.Button { theme: root.theme; text: '删除实例'; objectName: 'deleteComponentInstance'; visible: root.current.isDefault === false; enabled: root.manager && !root.manager.busy && ['installed','stopped','failed'].indexOf(root.current.state) >= 0; onClicked: root.manager.prepareDeleteInstance(root.current.id) }
                            }
                        }
                    }

                }
            }
        }
        ColumnLayout {
            visible: root.category === 'market'; enabled: visible; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
            Text { Layout.fillWidth: true; text: '从扩展源查找应用和组件'; color: root.theme.muted; wrapMode: Text.Wrap; font.pixelSize: 13 }
            Ui.TextField { theme: root.theme; objectName: 'marketSearch'; Layout.fillWidth: true; placeholderText: '搜索名称、简介、作者或标签'; text: root.marketQuery; onTextEdited: root.marketQuery = text }
            Flow { Layout.fillWidth: true; spacing: 8
                Ui.ComboBox { theme: root.theme; objectName: 'marketKindFilter'; width: 112; model: ['全部','应用','组件']; currentIndex: ['all','application','component'].indexOf(root.marketKind); onActivated: function(index) { root.marketKind = ['all','application','component'][index] } }
                Ui.ComboBox { theme: root.theme; objectName: 'marketSourceFilter'; visible: root.width >= 580 || root.showMarketFilters; width: Math.min(220, parent.width); model: root.sourceChoices; textRole: 'name'; currentIndex: root.sourceChoices.findIndex(function(source) { return source.id === root.marketSource }); onActivated: function(index) { root.marketSource = root.sourceChoices[index].id } }
                Ui.ComboBox { theme: root.theme; objectName: 'marketTagFilter'; visible: root.width >= 580 || root.showMarketFilters; width: 120; model: root.marketTags; currentIndex: root.marketTag ? root.marketTags.indexOf(root.marketTag) : 0; onActivated: function(index) { root.marketTag = index ? root.marketTags[index] : '' } }
                Ui.ComboBox { theme: root.theme; objectName: 'marketAuthorFilter'; visible: root.width >= 580 || root.showMarketFilters; width: 120; model: root.marketAuthors; currentIndex: root.marketAuthor ? root.marketAuthors.indexOf(root.marketAuthor) : 0; onActivated: function(index) { root.marketAuthor = index ? root.marketAuthors[index] : '' } }
                Ui.Button { theme: root.theme; objectName: 'marketFiltersToggle'; visible: root.width < 580; text: root.showMarketFilters ? '收起筛选' : '筛选'; onClicked: root.showMarketFilters = !root.showMarketFilters }
                Ui.Button { theme: root.theme; objectName: 'sourceButton'; text: '管理源'; onClicked: sourceDialog.open() }
            }
            ScrollView { id: marketScroll; objectName: 'marketScroll'; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                ScrollBar.vertical: Ui.ScrollBar { theme: root.theme; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom }
                ColumnLayout { width: marketScroll.availableWidth; spacing: 12
                    Text { Layout.fillWidth: true; visible: !root.activeSources.length; text: '尚未配置源。添加 Git 仓库地址或本地目录后查看可安装条目。'; color: root.theme.muted; wrapMode: Text.Wrap }
                    Repeater { model: root.filteredSources.filter(function(source) { return !source.revision })
                        ColumnLayout { required property var modelData; Layout.fillWidth: true
                            Text { Layout.fillWidth: true; text: (modelData.name || modelData.location) + '：尚未载入目录，请刷新。'; color: root.theme.muted; wrapMode: Text.Wrap }
                            Ui.Button { theme: root.theme; text: '刷新目录'; enabled: root.manager && !root.manager.busy; onClicked: root.manager.refreshSource(modelData.id) }
                        }
                    }
                    Text { objectName: 'marketEmptyState'; Layout.fillWidth: true; visible: root.filteredSources.length > 0 && root.marketEntries.length === 0 && root.filteredSources.every(function(source) { return !!source.revision }); text: '当前筛选下没有条目。'; color: root.theme.muted; wrapMode: Text.Wrap }
                    GridLayout { id: marketGrid; Layout.fillWidth: true; columns: marketScroll.availableWidth >= 900 ? 3 : marketScroll.availableWidth >= 580 ? 2 : 1; columnSpacing: 12; rowSpacing: 12
                      Repeater { model: root.marketEntries
                        Rectangle {
                            id: marketCard; required property var modelData; Layout.fillWidth: true; Layout.preferredWidth: (marketScroll.availableWidth - (marketGrid.columns - 1) * marketGrid.columnSpacing) / marketGrid.columns; implicitHeight: marketCardBody.implicitHeight + 32; radius: 10; color: root.theme.card; border.color: root.theme.border
                            ColumnLayout { id: marketCardBody; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; spacing: 8
                                RowLayout { Layout.fillWidth: true; spacing: 12
                                    Image { visible: !!marketCard.modelData.iconUrl; source: marketCard.modelData.iconUrl; Layout.preferredWidth: 52; Layout.preferredHeight: 52; fillMode: Image.PreserveAspectFit }
                                    ColumnLayout { Layout.fillWidth: true; spacing: 3
                                        Text { Layout.fillWidth: true; text: marketCard.modelData.manifest.name; textFormat: Text.PlainText; color: root.theme.ink; font.pixelSize: 16; font.weight: Font.DemiBold; wrapMode: Text.Wrap }
                                        Text { Layout.fillWidth: true; text: (marketCard.modelData.kind === 'application' ? '应用' : '组件') + ' · ' + marketCard.modelData.manifest.version + ' · ' + (marketCard.modelData.author || '') + ' · ' + marketCard.modelData.sourceName; textFormat: Text.PlainText; color: root.theme.muted; wrapMode: Text.Wrap; font.pixelSize: 12 }
                                    }
                                }
                                Text { Layout.fillWidth: true; visible: !!(marketCard.modelData.summary || marketCard.modelData.description); text: marketCard.modelData.summary || marketCard.modelData.description || ''; textFormat: Text.PlainText; color: root.theme.ink; wrapMode: Text.Wrap }
                                Text { Layout.fillWidth: true; visible: (marketCard.modelData.tags || []).length > 0; text: (marketCard.modelData.tags || []).join(' · '); textFormat: Text.PlainText; color: root.theme.muted; wrapMode: Text.Wrap; font.pixelSize: 12 }
                                Text { visible: root.marketOtherSource(marketCard.modelData); text: root.marketInstalledOrigin(marketCard.modelData); color: root.theme.muted; font.pixelSize: 12 }
                                Flow { Layout.fillWidth: true; spacing: 8
                                    Ui.Button { theme: root.theme; objectName: 'marketDetails_' + marketCard.modelData.manifest.id; visible: !!(marketCard.modelData.description || marketCard.modelData.readme || (marketCard.modelData.screenshots || []).length); text: '详情'; onClicked: { marketDetails.entry = marketCard.modelData; marketDetails.readmeText = marketCard.modelData.readme ? manager.marketReadme(marketCard.modelData.sourceDirectory, marketCard.modelData.readme) : ''; marketDetails.open() } }
                                    Ui.Button { theme: root.theme; objectName: 'installSource_' + marketCard.modelData.manifest.id; text: root.marketActionText(marketCard.modelData); enabled: root.manager && !root.manager.busy && text !== '已安装' && (marketCard.modelData.kind !== 'application' || (root.applicationHost && !root.applicationHost.busy)); onClicked: root.installMarketEntry(marketCard.modelData) }
                                    Ui.Button { theme: root.theme; objectName: 'changeSource_' + marketCard.modelData.manifest.id; visible: root.marketOtherSource(marketCard.modelData); text: '改用此源'; enabled: visible && root.manager && !root.manager.busy && (marketCard.modelData.kind !== 'application' || (root.applicationHost && !root.applicationHost.busy)); onClicked: root.installMarketEntry(marketCard.modelData) }
                                    Ui.Button { theme: root.theme; objectName: 'removeSource_' + marketCard.modelData.manifest.id; text: '卸载'; visible: marketCard.modelData.kind === 'component' ? !!root.removableComponent(marketCard.modelData) : root.matchingApplications(marketCard.modelData).some(function(app) { return !app.builtin }); enabled: visible && root.manager && !root.manager.busy && (marketCard.modelData.kind !== 'application' || (root.applicationHost && !root.applicationHost.busy)); onClicked: root.removeMarketEntry(marketCard.modelData) }
                                }
                            }
                        }
                      }
                    }
                }
            }
        }
    }
    Popup {
        id: marketDetails; objectName: 'marketDetailsDialog'; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(680, parent.width - 32); height: Math.min(620, parent.height - 32); padding: 20; modal: true; focus: true
        background: Rectangle { radius: 12; color: root.theme.card; border.color: root.theme.border }
        property var entry: ({})
        property string readmeText: ''
        onOpened: root.holdChanged('market-details', true)
        onClosed: root.holdChanged('market-details', false)
        contentItem: ColumnLayout { spacing: 12
            Text { Layout.fillWidth: true; text: marketDetails.entry.manifest ? marketDetails.entry.manifest.name : ''; textFormat: Text.PlainText; color: root.theme.ink; font.pixelSize: 18; wrapMode: Text.Wrap }
            ScrollView { id: detailsScroll; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                ScrollBar.vertical: Ui.ScrollBar { theme: root.theme; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom }
                ColumnLayout { width: detailsScroll.availableWidth; spacing: 12
                    Text { Layout.fillWidth: true; visible: !!marketDetails.entry.description; text: marketDetails.entry.description || ''; textFormat: Text.PlainText; color: root.theme.ink; wrapMode: Text.Wrap }
                    Text { Layout.fillWidth: true; visible: !!marketDetails.readmeText; text: marketDetails.readmeText; textFormat: Text.PlainText; color: root.theme.ink; wrapMode: Text.Wrap }
                    Repeater { model: marketDetails.entry.screenshots || []
                        Image { required property string modelData; Layout.fillWidth: true; Layout.preferredHeight: Math.min(360, implicitHeight); source: manager.marketAssetUrl(marketDetails.entry.sourceDirectory, modelData); fillMode: Image.PreserveAspectFit }
                    }
                }
            }
            Ui.Button { theme: root.theme; objectName: 'closeMarketDetails'; text: '关闭'; onClicked: marketDetails.close() }
        }
    }
    FolderDialog {
        id: installApplicationFolder; objectName: 'applicationDirectoryPicker'; title: '选择应用目录'
        onAccepted: { if (root.manager) root.manager.dismissNotice(); var identity = root.applicationHost.installPackage(selectedFolder.toString()); if (identity) root.selectedApplicationId = identity }
        onVisibleChanged: root.holdChanged('install-application-folder', visible)
    }
    FolderDialog {
        id: updateApplicationFolder; objectName: 'applicationUpdatePicker'; title: '选择应用更新目录'; property string applicationId: ''
        onAccepted: { if (root.manager) root.manager.dismissNotice(); root.applicationHost.updateApplication(applicationId, selectedFolder.toString()) }
        onVisibleChanged: root.holdChanged('update-application-folder', visible)
    }
    FolderDialog { id: componentFolder; title: '选择组件目录'; onAccepted: root.manager.loadDirectory(selectedFolder.toString()); onVisibleChanged: root.holdChanged('component-folder', visible) }
    Popup {
        id: removeApplicationDialog; objectName: 'applicationRemovalDialog'; property string applicationId: ''; property string applicationTitle: ''
        parent: Overlay.overlay; anchors.centerIn: parent; width: Math.min(440, parent.width - 32); padding: 20; modal: true; focus: true
        background: Rectangle { radius: 12; color: root.theme.card; border.color: root.theme.border }
        onOpened: root.holdChanged('remove-application', true)
        onClosed: root.holdChanged('remove-application', false)
        contentItem: ColumnLayout {
            spacing: 14
            Text { Layout.fillWidth: true; text: '卸载应用：' + removeApplicationDialog.applicationTitle; textFormat: Text.PlainText; color: root.theme.ink; font.pixelSize: 18; wrapMode: Text.Wrap }
            Text { Layout.fillWidth: true; text: '关闭应用并移除安装记录、授权和连接，保留应用数据。'; color: root.theme.muted; wrapMode: Text.Wrap }
            Flow {
                Layout.fillWidth: true; spacing: 8
                Ui.Button { theme: root.theme; objectName: 'cancelApplicationRemoval'; text: '取消'; onClicked: removeApplicationDialog.close() }
                Ui.Button { theme: root.theme; objectName: 'confirmApplicationRemoval'; text: '确认卸载'; primary: true; onClicked: { if (root.manager) root.manager.dismissNotice(); root.applicationHost.removeApplication(removeApplicationDialog.applicationId); removeApplicationDialog.close() } }
            }
        }
    }
    Popup {
        id: sourceApplicationRemoval; objectName: 'sourceApplicationRemoval'; property var targets: []
        parent: Overlay.overlay; anchors.centerIn: parent; width: Math.min(480, parent.width - 32); padding: 20; modal: true; focus: true
        background: Rectangle { radius: 12; color: root.theme.card; border.color: root.theme.border }
        onOpened: root.holdChanged('source-application-removal', true)
        onClosed: root.holdChanged('source-application-removal', false)
        contentItem: ColumnLayout { spacing: 14
            Text { Layout.fillWidth: true; text: '选择要卸载的应用'; color: root.theme.ink; font.pixelSize: 18; wrapMode: Text.Wrap }
            Ui.ComboBox { id: removalTarget; objectName: 'sourceApplicationRemovalTarget'; theme: root.theme; Layout.fillWidth: true; model: sourceApplicationRemoval.targets; textRole: 'title'; displayText: currentIndex < 0 ? '请选择应用' : currentText }
            Flow { Layout.fillWidth: true; spacing: 8
                Ui.Button { theme: root.theme; text: '取消'; onClicked: sourceApplicationRemoval.close() }
                Ui.Button { theme: root.theme; objectName: 'selectSourceApplicationRemoval'; text: '继续'; primary: true; enabled: removalTarget.currentIndex >= 0; onClicked: { var target = sourceApplicationRemoval.targets[removalTarget.currentIndex]; sourceApplicationRemoval.close(); removeApplicationDialog.applicationId = target.applicationId; removeApplicationDialog.applicationTitle = target.title; removeApplicationDialog.open() } }
            }
        }
    }
    Popup {
        id: sourceApplicationUpdate; objectName: 'sourceApplicationUpdate'; property var entry: ({}); property var targets: []
        parent: Overlay.overlay; anchors.centerIn: parent; width: Math.min(480, parent.width - 32); padding: 20; modal: true; focus: true
        background: Rectangle { radius: 12; color: root.theme.card; border.color: root.theme.border }
        onOpened: root.holdChanged('source-application-update', true)
        onClosed: root.holdChanged('source-application-update', false)
        contentItem: ColumnLayout { spacing: 14
            Text { Layout.fillWidth: true; text: '选择要从此源更新的应用'; color: root.theme.ink; font.pixelSize: 18; wrapMode: Text.Wrap }
            Text { Layout.fillWidth: true; text: '保留所选应用的身份、数据和组件连接。'; color: root.theme.muted; wrapMode: Text.Wrap }
            Ui.ComboBox { id: sourceApplicationTarget; objectName: 'sourceApplicationTarget'; theme: root.theme; Layout.fillWidth: true; model: sourceApplicationUpdate.targets; textRole: 'title'; displayText: currentIndex < 0 ? '请选择应用' : currentText }
            Flow { Layout.fillWidth: true; spacing: 8
                Ui.Button { theme: root.theme; text: '取消'; onClicked: sourceApplicationUpdate.close() }
                Ui.Button { theme: root.theme; objectName: 'confirmSourceApplicationUpdate'; text: '更新所选应用'; primary: true; enabled: sourceApplicationTarget.currentIndex >= 0; onClicked: { var entry = sourceApplicationUpdate.entry; root.applicationHost.updateSourceApplication(sourceApplicationUpdate.targets[sourceApplicationTarget.currentIndex].applicationId, entry.sourceId, entry.manifest.id, entry.revision); sourceApplicationUpdate.close() } }
            }
        }
    }
    Popup {
        id: sourceDialog; objectName: 'sourceDialog'; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(760, parent.width - 32); height: Math.min(570, parent.height - 32); padding: 20; modal: true; focus: true
        background: Rectangle { radius: 12; color: root.theme.card; border.color: root.theme.border }
        onOpened: root.holdChanged('component-sources', true)
        onClosed: root.holdChanged('component-sources', false)
        contentItem: ColumnLayout {
            spacing: 12
            Text { text: '管理源'; color: root.theme.ink; font.pixelSize: 18 }
            Ui.TextField { theme: root.theme; id: sourceLocation; objectName: 'sourceLocation'; placeholderText: 'Git 仓库地址或本地目录'; Layout.fillWidth: true; enabled: root.manager && !root.manager.busy }
            Ui.TextField { theme: root.theme; id: sourceRef; objectName: 'sourceRef'; placeholderText: '分支、标签或提交（留空使用默认）'; Layout.fillWidth: true; enabled: root.manager && !root.manager.busy }
            Ui.Button { theme: root.theme; objectName: 'addSource'; text: '添加源'; enabled: root.manager && !root.manager.busy && sourceLocation.text.trim().length > 0; onClicked: root.manager.addSource(sourceLocation.text, sourceRef.text) }
            Ui.Button { theme: root.theme; objectName: 'toggleArchivedSources'; visible: root.archivedSources.length > 0; text: root.showArchivedSources ? '隐藏历史来源' : '查看历史来源（' + root.archivedSources.length + '）'; onClicked: root.showArchivedSources = !root.showArchivedSources }
            ScrollView {
                id: sourceScroll; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                ScrollBar.vertical: Ui.ScrollBar { theme: root.theme }
                ColumnLayout {
                    width: sourceScroll.availableWidth; spacing: 14
                    Repeater {
                        model: root.activeSources.concat(root.showArchivedSources ? root.archivedSources : [])
                        ColumnLayout {
                            id: sourceRow; required property var modelData; Layout.fillWidth: true; spacing: 8
                            Text { Layout.fillWidth: true; text: sourceRow.modelData.name || sourceRow.modelData.location; color: root.theme.ink; wrapMode: Text.Wrap }
                            Text { Layout.fillWidth: true; text: sourceRow.modelData.location + (sourceRow.modelData.ref ? ' · ' + sourceRow.modelData.ref : '') + (sourceRow.modelData.archived ? ' · 历史来源' : ''); color: root.theme.muted; wrapMode: Text.WrapAnywhere; font.pixelSize: 12 }
                            Text { Layout.fillWidth: true; text: sourceRow.modelData.defaultError || ''; visible: text.length > 0; color: root.theme.error; wrapMode: Text.Wrap }
                            Ui.Button { theme: root.theme; visible: !sourceRow.modelData.archived; text: sourceRow.modelData.pending ? '正在安装…' : sourceRow.modelData.defaultError ? '重试安装' : '检查更新'; enabled: root.manager && !root.manager.busy && !sourceRow.modelData.pending; onClicked: sourceRow.modelData.defaultError ? root.manager.retryDefault(sourceRow.modelData.id) : root.manager.refreshSource(sourceRow.modelData.id) }
                        }
                    }
                }
            }
            Ui.Button { theme: root.theme; objectName: 'closeSources'; text: '关闭'; onClicked: sourceDialog.close() }
        }
    }
}
