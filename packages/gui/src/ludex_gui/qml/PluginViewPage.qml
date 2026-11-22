import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// One plugin view: a table or a label/value panel. A row action asks first and runs only after Yes.
Item {
    id: view
    required property var page   // the ViewController
    property int selected: -1
    readonly property var rows: page.rows
    readonly property var actions: selected >= 0 && selected < rows.length ? rows[selected].actions : []
    readonly property int columnCount: Math.max(1, page.columns.length)
    readonly property bool detail: page.columns.length === 2 && page.columns[0] === "Field" && page.columns[1] === "Value"

    onVisibleChanged: if (visible) page.ensureLoaded()
    Connections {
        target: view.page
        function onChanged() { if (view.selected >= view.rows.length) view.selected = -1 }
    }

    function askAction(actionIndex) {
        confirm.row = selected
        confirm.action = actionIndex
        confirm.generation = page.generation
        confirm.question = page.confirmText(selected, actionIndex)
        if (confirm.question !== "") {
            confirm.open()
        }
    }

    Dialog {
        id: confirm
        objectName: "confirm"
        property int row: -1
        property int action: -1
        property int generation: -1
        property string question: ""
        modal: true
        anchors.centerIn: Overlay.overlay
        padding: 20
        background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
        header: Txt { text: "Confirm"; font.bold: true; font.pixelSize: 16; padding: 20; bottomPadding: 0 }
        contentItem: Txt { text: confirm.question; wrapMode: Text.Wrap; width: 360; lineHeight: 1.2 }
        footer: DialogButtonBox {
            padding: 16
            spacing: 8
            background: Item { }
            delegate: Btn { }
            standardButtons: Dialog.Yes | Dialog.Cancel
        }
        onOpened: standardButton(Dialog.Cancel).forceActiveFocus()
        onAccepted: {
            if (!view.page.runAction(generation, row, action)) {
                backend.notify("The list changed; choose the action again.", true)
            }
        }
    }

    Popup {
        id: menu
        objectName: "actions"
        x: actionsButton.x
        y: actionsButton.y + actionsButton.height + 4
        parent: actionsButton.parent
        padding: 6
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: if (actionButtons.count > 0) actionButtons.itemAt(0).forceActiveFocus(Qt.TabFocusReason)
        background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
        contentItem: Column {
            spacing: 4
            Repeater {
                id: actionButtons
                model: view.actions
                delegate: Btn {
                    required property var modelData
                    required property int index
                    width: 280
                    text: modelData.label + "   (" + modelData.command + ")"
                    onClicked: { menu.close(); view.askAction(index) }
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Txt { text: view.page.title; font.pixelSize: Theme.title; font.bold: true; elide: Text.ElideRight; Layout.maximumWidth: parent.width * 0.5 }
            Txt { Layout.fillWidth: true; text: view.page.text; color: view.page.error !== "" ? Theme.bad : Theme.muted; elide: Text.ElideRight }
            Btn {
                id: actionsButton
                text: "Actions…"
                enabled: view.page.busy === "" && view.actions.length > 0
                onClicked: menu.open()
            }
            Btn { text: "Refresh"; enabled: view.page.busy === ""; onClicked: view.page.load() }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radius
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            clip: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                RowLayout {
                    visible: !view.detail && view.page.columns.length > 0
                    Layout.fillWidth: true
                    Layout.margins: 12
                    Layout.rightMargin: 90
                    spacing: 12
                    Repeater {
                        model: view.page.columns
                        delegate: Txt { required property string modelData; Layout.fillWidth: true; Layout.preferredWidth: 1; text: modelData; color: Theme.muted; font.bold: true; elide: Text.ElideRight }
                    }
                }
                ListView {
                    id: list
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: view.rows
                    activeFocusOnTab: true
                    keyNavigationEnabled: true
                    currentIndex: -1
                    onCurrentIndexChanged: view.selected = currentIndex
                    Keys.onReturnPressed: if (view.actions.length > 0) menu.open()
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        id: line
                        required property var modelData
                        required property int index
                        width: list.width
                        height: cells.implicitHeight + 20
                        color: view.selected === index ? Theme.surface3 : (index % 2 ? Theme.surface : Theme.surface2)
                        RowLayout {
                            id: cells
                            anchors.fill: parent
                            anchors.margins: 12
                            anchors.topMargin: 10
                            anchors.bottomMargin: 10
                            anchors.rightMargin: 90
                            spacing: 12
                            Repeater {
                                model: line.modelData.cells
                                delegate: Txt {
                                    required property string modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: view.detail ? (index === 0 ? 1 : 3) : 1
                                    Layout.alignment: Qt.AlignTop
                                    text: modelData
                                    wrapMode: Text.Wrap
                                    color: view.detail && index === 0 ? Theme.muted : Theme.text
                                }
                            }
                        }
                        Chip {
                            visible: line.modelData.actions.length > 0
                            text: "actions"
                            interactive: false
                            anchors.right: parent.right
                            anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: list.currentIndex = line.index
                            onDoubleClicked: { list.currentIndex = line.index; if (view.actions.length > 0) menu.open() }
                        }
                    }
                    Txt {
                        anchors.centerIn: parent
                        visible: list.count === 0
                        text: view.page.text
                        color: Theme.muted
                    }
                }
            }
        }
    }
}
