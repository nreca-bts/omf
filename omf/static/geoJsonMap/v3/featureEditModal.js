export { FeatureEditModal, zoom };
import { Feature, UnsupportedOperationError } from './feature.js';
import { PropTable } from '../v4/ui-components/prop-table/prop-table.js';
import { FeatureController } from './featureController.js';
import { LeafletLayer } from './leafletLayer.js';
import { IconLabelButton } from '../v4/ui-components/iconlabel-button/iconlabel-button.js';
import { Validity } from '../v4/mvc/models/validity/validity.js';

class FeatureEditModal { // implements ObserverInterface, ModalInterface

    #controller;    // - ControllerInterface instance
    #propTable;     // - A PropTable instance
    #observable;    // - A single ObservableInterface instance
    #removed;       // - Whether this FeatureEditModal instance has already been deleted
    static #nonDeletableProperties = ['name', 'object', 'from', 'to', 'parent', 'latitude', 'longitude', 'treeKey', 'CMD_command'];

    /**
     * @param {Feature} observable - a single ObservableInterface instance
     * @param {FeatureController} controller - a ControllerInterface instance
     * @returns {undefined}
     */
    constructor(observable, controller) {
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argumnet must be instanceof Feature.');
        }
        if (!(controller instanceof FeatureController)) {
            throw Error('The "controller" argument must be instanceof FeatureController.');
        }
        this.#controller = controller;
        this.#propTable = null;
        this.#observable = observable;
        this.#observable.registerObserver(this);
        this.#removed = false;
        this.renderContent();
    }

    // *******************************
    // ** ObserverInterface methods ** 
    // *******************************

    /**
     * - Remove this ObserverInterface instance (i.e. "this") from the ObservableInterface instance (i.e. "observable") that has been deleted, and
     *   perform other actions as needed
     * @param {Feature} observable - an ObservableInterface instance
     * @returns {undefined}
     */
    handleDeletedObservable(observable) {
        // - The function signature above is part of the ObserverInterface API. The implementation below is not
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argument must be instanceof Feature.');
        }
        if (!this.#removed) {
            this.remove();
        }
    }

    /**
     *
     */
    handleNewObservable(observable) {
        // - The function signature above is part of the ObserverInterface API. The implementation below is not
        throw new UnsupportedOperationError();
    }

    /**
     * - Update this ObserverInterface instance (i.e. "this") based on the coordinates of the ObservableInterface instance (i.e. "observable") that
     *   have just changed and perform other actions as needed
     * @param {Feature} observable - an ObservableInterface instance
     * @param {Array} oldCoordinates - the old coordinates of the observable prior to the change in coordinates
     * @returns {undefined}
     */
    handleUpdatedCoordinates(observable, oldCoordinates) {
        // - The function signature above is part of the ObserverInterface API. The implementation below is not
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argument must be instanceof Feature.');
        }
        if (!(oldCoordinates instanceof Array)) {
            throw TypeError('The "oldCoordinates" argument must be an array.');
        }
        this.refreshContent();
    }

    /**
     * - Update this ObserverInstance (i.e. "this") based on the property of the ObservableInterface instance (i.e. "observable") that has just
     *   changed and perform other actions as needed
     * @param {Feature} observable - an ObservableInterface instance
     * @param {string} propertyKey - the property key of the property that has been created/changed/deleted in the observable
     * @param {(string|Object)} oldPropertyValue - the previous value of the property that has been created/changed/deleted in the observable
     * @param {string} namespace - the namespace of the property that has been created/changed/deleted in the observable
     * @returns {undefined}
     */
    handleUpdatedProperty(observable, propertyKey, oldPropertyValue, namespace='treeProps') {
        // - The function signature above is part of the ObserverInterface API. The implementation below is not
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argument must be instanceof Feature.');
        }
        if (typeof propertyKey !== 'string') {
            throw TypeError('The "propertyKey" argument must be a string.');
        }
        if (typeof namespace !== 'string') {
            throw TypeError('The "namespace" argument must be a string.');
        }
        this.refreshContent();
    }

    // ****************************
    // ** ModalInterface methods **
    // ****************************

    getDOMElement() {
        return this.#propTable.div;
    }

    /**
     * @returns {boolean}
     */
    isRemoved() {
        return this.#removed;
    }

    /**
     * - Refresh aspects of the modal so that I don't have to re-render the whole thing
     * @returns {undefined}
     */
    refreshContent() {
        const tableState = {};
        // - Don't grab a row that was added with the "+" button, if it exists
        [...this.#propTable.div.getElementsByTagName('tr')].filter(tr => tr.querySelector('span[data-property-key]') !== null).forEach(tr => {
            const span = tr.getElementsByTagName('span')[0];
            let namespace = span.dataset.propertyNamespace;
            // - latitude and longitude don't exist in any property namespace
            if (namespace === undefined) {
                namespace = null;
            }
            tableState[span.dataset.propertyKey] = {
                propertyNamespace: namespace,
                propertyTableRow: tr,
                // - This is either an input or a span
                propertyValueElement: tr.children[2].children[0].children[0]
            }
        });
        const tableKeys = Object.keys(tableState);
        // - Don't worry about inserting a new property into the table in sorted order. It will be sorted the next time that the table is rendered
        for (const [key, val] of Object.entries(this.#observable.getProperties('treeProps'))) {
            // - First, compare the observable's state to the table state. If the observable's state has a property that is not in the table state,
            //   add a row to the table
            if (!tableKeys.includes(key)) {
                // - Don't display "from", "to", or "type" for parent-child lines
                if (['from', 'to', 'type'].includes(key) && this.#observable.isParentChildLine()) {
                    continue;
                }
                const keySpan = document.createElement('span');
                keySpan.textContent = key;
                keySpan.dataset.propertyKey = key;
                keySpan.dataset.propertyNamespace = 'treeProps';
                this.#propTable.insertTBodyRow({elements: [this.#getDeletePropertyButton(key), keySpan, this.#getValueTextInput(key, val)], position: 'beforeEnd'});
            // - Second, if the table has the already key, update the table
            } else {
                const valueElement = tableState[key].propertyValueElement;
                if (valueElement instanceof HTMLInputElement) {
                    valueElement.value = val.toString();
                } else if (valueElement instanceof HTMLSpanElement) {
                    valueElement.textContent = val.toString();
                }
            }
        }
        for (const key of ['latitude', 'longitude']) {
            // - No lines or configuration objects should ever display "latitude" or "longitude" in their table to begin with
            if (tableKeys.includes(key)) {
                const [lon, lat] = this.#observable.getCoordinates();
                const valueElement = tableState[key].propertyValueElement;
                if (valueElement instanceof HTMLInputElement) {
                    if (key === 'latitude') {
                        valueElement.value = lat;
                    } else {
                        valueElement.value = lon;
                    }
                }
            }
        }
        // - Now compare the table's state to the observable's state. If the table's state has a property that is not in the observable's state,
        //   remove the row from the table
        for (const [key, obj] of Object.entries(tableState)) {
            if (['latitude', 'longitude'].includes(key)) {
                continue;
            }
            if (!this.#observable.hasProperty(key, obj.propertyNamespace)) {
                obj.propertyTableRow.remove();
            }
        }
    }

    /**
     * @returns {undefined}
     */
    remove() {
        if (!this.#removed) {
            this.#observable.removeObserver(this);
            this.#observable = null;
            this.#propTable.div.remove();
            this.#removed = true;
        }
    }

    /**
     * - Render the modal for the first time
     * @returns {undefined}
     */
    renderContent() {
        const propTable = new PropTable();
        propTable.div.classList.add('featureEditModal');
        if (this.#observable.hasProperty('treeKey', 'meta')) {
            this.#renderOmfFeature(propTable);
        } else {
            this.#renderArbitraryFeature(propTable);
        }
        propTable.div.addEventListener('click', function(e) {
            // - Don't let clicks on the table cause the popup to close
            e.stopPropagation();
        });
        if (this.#propTable === null) {
            this.#propTable = propTable;
        }
        if (document.body.contains(this.#propTable.div)) {
            this.#propTable.div.replaceWith(propTable.div);
            this.#propTable = propTable;
        }
    }

    // *********************
    // ** Private methods ** 
    // *********************

    /**
     * @param {Event} event - a standard mouse click event
     */
    #addObservableWithClick(event) {
        const mapDiv = document.getElementById('map');
        mapDiv.style.cursor = 'crosshair';
        LeafletLayer.map.on('click', (e) => {
            // - If the user clicks on an "add" button multiple times or clicks on a node add button followed by a line add button, it's fine. This
            //   event listener is only registered on each button once per button. As soon as the first button is clicked, that's the event handler
            //   that will execute first on the map. Since this event handler also removes all "click" event handlers from the map, all subsequent add
            //   operation event handlers will be removed before they exeucte
            LeafletLayer.map.off('click');
            mapDiv.style.removeProperty('cursor');
            try {
                const observable = this.#getObservableFromComponent(this.#observable, [e.latlng.lat, e.latlng.lng]);
                this.#controller.addObservables([observable]);
            } catch (e) {
                alert(e.message);
            }
        });
    }

    /**
     * - Add a configuration object to the data
     * @returns {HTMLButtonElement}
     */
    #getAddConfigurationObjectButton() {
        let button = new IconLabelButton({paths: IconLabelButton.getCirclePlusPaths(), viewBox: '0 0 24 24', text: 'Add a config object'});
        button.button.classList.add('-green');
        button.button.getElementsByClassName('icon')[0].classList.add('-white');
        button.button.getElementsByClassName('label')[0].classList.add('-white');
        button = button.button;
        button.addEventListener('click', () => {
            try {
                const observable = this.#getObservableFromComponent(this.#observable);
                this.#controller.addObservables([observable]);
            } catch (e) {
                alert(e.message);
            }
        });
        return button;
    }

    /**
     * - Add a line. If the "from" and "to" values are valid, use them. If they aren't, grab the two closest nodes to the click on the map and connect
     *   the line to those nodes
     * @returns {HTMLButtonElement}
     */
    #getAddLineButton() {
        let button = new IconLabelButton({
            paths: IconLabelButton.getCirclePlusPaths(),
            viewBox: '0 0 24 24',
            text: 'Add a line',
            tooltip: 'Add a new line to the data by clicking on this button then clicking on the map. If valid values for the "from" and "to"' +
                ' properties are specified, the line will connect to those objects. Otherwise, the line will connect to the two nodes that were' +
                ' closest to the map click.'
        });
        button.button.classList.add('-green');
        button.button.getElementsByClassName('icon')[0].classList.add('-white');
        button.button.getElementsByClassName('label')[0].classList.add('-white');
        button = button.button;
        button.addEventListener('click', this.#addObservableWithClick.bind(this));
        return button;
    }

    /**
     * - Add a node to the map by clicking on the map
     * @returns {HTMLDivElement}
     */
    #getAddNodeButton() {
        let button = new IconLabelButton({
            paths: IconLabelButton.getCirclePlusPaths(),
            viewBox: '0 0 24 24',
            text: 'Add a node',
            tooltip: 'Add a new node to the data by clicking on this button then clicking on the map. If the node is a child and a valid value for' +
                ' the "parent" property is specified, the child will connect to that parent. Otherwise, the child will connect to parent that was' +
                ' closest to the map click.'
        });
        button.button.classList.add('-green');
        button.button.getElementsByClassName('icon')[0].classList.add('-white');
        button.button.getElementsByClassName('label')[0].classList.add('-white');
        button = button.button;
        button.addEventListener('click', this.#addObservableWithClick.bind(this));
        return button;
    }
    
    /**
     * @returns {HTMLButtonElement}
     */
    #getAddPropertyButton() {
        let button = new IconLabelButton({paths: IconLabelButton.getCirclePlusPaths(), viewBox: '0 0 24 24', tooltip: 'Add new property'});
        button.button.classList.add('-green');
        button.button.getElementsByClassName('icon')[0].classList.add('-white');
        button = button.button;
        const that = this;
        button.addEventListener('click', function() {
            const deletePlaceholder = document.createElement('span');
            const keyInputPlaceholder = document.createElement('span');
            const valueInputPlaceholder = document.createElement('span');
            that.#propTable.insertTBodyRow({elements: [deletePlaceholder, keyInputPlaceholder, valueInputPlaceholder], position: 'beforeEnd'});
            that.#insertKeyTextInput(deletePlaceholder, keyInputPlaceholder, valueInputPlaceholder);
        });
        return button;
    }

    /**
     * @returns {HTMLDivElement}
     */
    #getDeleteFeatureButton() {
        let button = new IconLabelButton({paths: IconLabelButton.getTrashCanPaths(), viewBox: '0 0 24 24', tooltip: 'Delete object'});
        button.button.classList.add('-red');
        button.button.getElementsByClassName('icon')[0].classList.add('-white');
        button = button.button;
        button.addEventListener('click', () => {
            this.#controller.deleteObservables([this.#observable]);
        });
        return button;
    }
    
    /**
     * @param {string} propertyKey
     * @returns {HTMLButtonElement} a button that can be clicked on to remove a property from an ObservableInterface instance
     */
    #getDeletePropertyButton(propertyKey) {
        if (typeof propertyKey !== 'string') {
            throw TypeError('"propertyKey" argument must be a string.');
        }
        let button = new IconLabelButton({paths: IconLabelButton.getTrashCanPaths(), viewBox: '0 0 24 24', tooltip: 'Delete property'});
        button.button.classList.add('-red');
        button.button.getElementsByClassName('icon')[0].classList.add('-white');
        button = button.button;
        const that = this;
        button.addEventListener('click', function(e) {
            that.#controller.deleteProperty([that.#observable], propertyKey);
            // - This is code is required for a transitionalDeleteButton to remove the row
            let parentElement = this.parentElement;
            while (!(parentElement instanceof HTMLTableRowElement)) {
                parentElement = parentElement.parentElement;
            }
            parentElement.remove();
            e.stopPropagation();
        });
        return button;
    }

    /**
     * - TODO: move this into the controller? Wouldn't be so bad if I did. Actually I should because of mass add. But mass add should just be another
     *   button so this function can stay here.
     * @param {Feature} component - a component feature
     * @param {Array} [coordinates=null] - an array of coordinates in [<lat>, <lon>] format that the new feature should have instead of the
     *  coordinates that were in the component
     * @throws an error if it isn't possible to get a valid feature from a component
     * @returns {Feature} a feature that can be added to the graph
     */
    #getObservableFromComponent(component, coordinates=null) {
        if (!(component instanceof Feature)) {
            throw TypeError('The "component" argument must be instanceof Feature.');
        }
        // 1) Clone the component to create an observable and correct errors that are possible to correct
        const geometry = {
            type: component.getCoordinates()[0] instanceof Array ? 'LineString' : 'Point',
            // - Node components come with [0, 0] coordinates from the back-end, line components come with [[0, 0], [0, 0]] coordinates from the
            //   back-end and configuration object components come with [null, null] coordinates from the back-end. This is important for the
            //   isNode(), isLine(), and isConfigurationObject() functions
            coordinates: structuredClone(component.getCoordinates())
        };;
        const feature = new Feature({
            geometry: geometry,
            properties: {
                // - Components come with a treeKey in the from of "component:<number>" from the back-end. A cloned component feature is only given a
                //   valid treeKey (and a valid name) by a FeatureController when it is inserted into the graph because that's the only way to ensure
                //   that the next max number is being used
                treeKey: component.getProperty('treeKey', 'meta'),
                treeProps: structuredClone(component.getProperties('treeProps'))
            },
            type: 'Feature'
        });
        // - If the feature is a line, get the coordinates of its nodes
        if (feature.isLine()) {
            // - If the feature has valid "from" and "to" properties, add the line between those nodes
            const fromValidity = this.#controller.observableGraph.getLineConnectionNameValidity(feature, feature.getProperty('from'));
            const toValidity = this.#controller.observableGraph.getLineConnectionNameValidity(feature, feature.getProperty('to'));
            const fromToValidity = new Validity(false);
            let fromKey;
            let toKey;
            if (fromValidity.isValid && toValidity.isValid) {
                fromKey = this.#controller.observableGraph.getKeyForComponent(feature.getProperty('from'));
                toKey = this.#controller.observableGraph.getKeyForComponent(feature.getProperty('to'));
                if (fromKey !== toKey) {
                    fromToValidity.isValid = true;
                } else {
                    throw Error('The line was not added because lines may not start and end at the same node.');
                }
            }
            if (fromToValidity.isValid) {
                const { sourceLat, sourceLon, targetLat, targetLon } = this.#controller.observableGraph.getLineLatLon(fromKey, toKey);
                geometry.coordinates = [[sourceLon, sourceLat], [targetLon, targetLat]];
            // - If the feature does not have valid "from" and "to" properties, add the line to the nodes that are closest to the coordinates
            } else {
                // - Lines can be connected to other lines, but I don't automatically do that
                // - Lines can be connect to child nodes, but I don't automatically do that
                const possibleNodes = this.#controller.observableGraph.getObservables(ob => ob.isNode() && !ob.hasProperty('parent'));
                if (possibleNodes.length < 2) {
                    throw Error('The line was not added because there are no valid nodes that this line could connect to.');
                }
                let [fromLon, fromLat] = possibleNodes[0].getCoordinates();
                let fromNodeDistanceDiff = Math.abs(coordinates[1] - fromLon) + Math.abs(coordinates[0] - fromLat);
                let fromName = possibleNodes[0].getProperty('name');
                let [toLon, toLat] = possibleNodes[1].getCoordinates();
                let toNodeDistanceDiff = Math.abs(coordinates[1] - toLon) + Math.abs(coordinates[0] - toLat);
                let toName = possibleNodes[1].getProperty('name');
                for (let i = 2; i < possibleNodes.length; i++) {
                    const [lon, lat] = possibleNodes[i].getCoordinates();
                    const distanceDiff = Math.abs(coordinates[1] - lon) + Math.abs(coordinates[0] - lat);
                    if (distanceDiff < fromNodeDistanceDiff) {
                        if (fromNodeDistanceDiff > toNodeDistanceDiff) {
                            fromLon = lon;
                            fromLat = lat;
                            fromNodeDistanceDiff = distanceDiff;
                            fromName = possibleNodes[i].getProperty('name');
                            continue;
                        } else {
                            toLon = lon;
                            toLat = lat;
                            toNodeDistanceDiff = distanceDiff;
                            toName = possibleNodes[i].getProperty('name');
                            continue;
                        }
                    }
                    if (distanceDiff < toNodeDistanceDiff) {
                        if (toNodeDistanceDiff > fromNodeDistanceDiff) {
                            toLon = lon;
                            toLat = lat;
                            toNodeDistanceDiff = distanceDiff;
                            toName = possibleNodes[i].getProperty('name');
                            continue;
                        } else {
                            fromLon = lon;
                            fromLat = lat;
                            fromNodeDistanceDiff = distanceDiff;
                            fromName = possibleNodes[i].getProperty('name');
                        }
                    }
                }
                feature.setProperty('from', fromName);
                feature.setProperty('to', toName);
                geometry.coordinates = [[fromLon, fromLat], [toLon, toLat]];
            }
        } else if (feature.isNode()) {
            // - If the feature is a node, use the coordinates from the map click
            if (coordinates !== null) {
                geometry.coordinates = [coordinates[1], coordinates[0]];
            } else {
                throw Error('Adding a node requires coordinates from a map click.');
            }
            if (feature.isChild()) {
                const validity = this.#controller.observableGraph.getLineConnectionNameValidity(feature, feature.getProperty('parent'));
                if (!validity.isValid) {
                    const possibleParents = this.#controller.observableGraph.getObservables(ob => ob.isNode() && !ob.hasProperty('parent'));
                    if (possibleParents.length < 1) {
                        throw Error('The child was not added because there were no valid parents that this child could connect to.');
                    }
                    let [parentLon, parentLat] = possibleParents[0].getCoordinates();
                    let parentDistanceDiff = Math.abs(coordinates[1] - parentLon) + Math.abs(coordinates[0] - parentLat);
                    let parentName = possibleParents[0].getProperty('name');
                    for (const parent of possibleParents) {
                        const [lon, lat] = parent.getCoordinates();
                        const distanceDiff = Math.abs(coordinates[1] - lon) + Math.abs(coordinates[0] - lat);
                        if (distanceDiff < parentDistanceDiff) {
                            parentDistanceDiff = distanceDiff;
                            parentName = parent.getProperty('name');
                        }
                    }
                    feature.setProperty('parent', parentName);
                }
            }
        }
        // 2) Detect any invalid property values that I cannot fix and throw an exception
        if (feature.hasProperty('type') && feature.getProperty('type').toLowerCase() === 'parentchild') {
            throw Error('The "type" property may not have a value of "parentChild".');
        }
        if (feature.hasProperty('treeKey')) {
            throw Error('An object may not have the property "treeKey".');
        }
        return feature;
    }

    /**
     * - Return a text input that can be viewed in a modal
     * @param {string} propertyKey
     * @param {} [propertyValue=null]
     * @returns {HTMLInputElement} a text input that can be edited to change a property value in an ObservableInterface instance
     */
    #getValueTextInput(propertyKey, propertyValue=null) {
        if (typeof propertyKey !== 'string') {
            throw TypeError('The "propertyKey" argument must be typeof string.');
        }
        const input = document.createElement('input');
        if (propertyValue === null) {
            //- Do nothing. A new property was just added so the value text input should be blank
        } else {
            input.value = propertyValue.toString();
        }
        let originalValue = input.value;
        const that = this;
        input.addEventListener('change', function() {
            const inputValue = this.value.trim();
            if (that.#observable.isComponentFeature()) {
                // - Don't perform validation. Since latitude and longitude are no longer displayed in component tables, there's no way for the user
                //   to fail validation and trigger an error
                that.#controller.setProperty([that.#observable], propertyKey, inputValue);
            } else {
                if (that.#valueTextInputIsValid(propertyKey, inputValue)) {
                    if (['latitude', 'longitude'].includes(propertyKey)) {
                        if (that.#observable.isNode()) {
                            const [lon, lat] = that.#observable.getCoordinates();
                            if (propertyKey === 'latitude') {
                                that.#controller.setCoordinates([that.#observable], [lon, inputValue]);
                            } else {
                                that.#controller.setCoordinates([that.#observable], [inputValue, lat]);
                            }
                        }
                    } else {
                        that.#controller.setProperty([that.#observable], propertyKey, inputValue);
                    }
                    originalValue = inputValue;
                } else {
                    this.value = originalValue;
                }
            }
        });
        return input;
    }
    
    /**
     * @returns {HTMLButtonElement}
     */
    #getZoomButton() {
        let button = new IconLabelButton({paths: IconLabelButton.getPinPaths(), viewBox: '0 0 24 24', tooltip: 'Zoom to object'});
        button.button.classList.add('-blue');
        button.button.getElementsByClassName('icon')[0].classList.add('-white');
        button = button.button;
        button.addEventListener('click', zoom.bind(null, [this.#observable]));
        return button;
    }

    /**
     * @param {Node} deletePlaceholder - a document node that will be replaced by a "delete property" button
     * @param {Node} keyInputPlaceholder - a document node that will be replaced by this key input
     * @param {Node} valueInputPlaceholder - a document node that will be replaced by a value input 
     * @returns {undefined}
     */
    #insertKeyTextInput(deletePlaceholder, keyInputPlaceholder, valueInputPlaceholder) {
        const input = document.createElement('input');
        keyInputPlaceholder.replaceWith(input);
        const transitionalDeleteButton = this.#getDeletePropertyButton('');
        deletePlaceholder.replaceWith(transitionalDeleteButton);
        const that = this;
        let originalValue = input.value;
        input.addEventListener('change', function() {
            const inputValue = this.value.trim();
            // - If the input value isn't valid, just don't create a text input for the value and don't update the feature's properties
            if (that.#keyTextInputIsValid(inputValue)) {
                let parentElement = this.parentElement;
                while (!(parentElement instanceof HTMLTableRowElement)) {
                    parentElement = parentElement.parentElement;
                }
                parentElement.remove();
                that.#controller.setProperty([that.#observable], inputValue, '', 'treeProps');
            } else {
                input.value = originalValue;
            }
        });
    }

    /**
     * @param {string} inputValue
     * @returns {boolean}
     */
    #keyTextInputIsValid(inputValue) {
        // - I am no longer always converting to lowercase because names are case-sensitive and therefore other properties should be too
        if (FeatureEditModal.#nonDeletableProperties.includes(inputValue)) {
            alert(`The following properties cannot be added to objects: ${FeatureEditModal.#nonDeletableProperties}.`);
            return false;
        } else if (inputValue === '') {
            return false;
        } else if (this.#observable.hasProperty(inputValue)) {
            alert(`The property "${inputValue}" could not be added because this object already has this property.`);
            return false;
        }
        return true;
    }

    /**
     * - Render normal features
     * @returns {undefined}
     */
    #renderOmfFeature(propTable) {
        const sortedEntries = Object.entries(this.#observable.getProperties('treeProps'));
        sortedEntries.sort((a, b) => a[0].localeCompare(b[0], 'en', {numeric: true}));
        // - If the feature has the "object" property, add it to the top of the table
        let i = 0;
        while (i < sortedEntries.length) {
            if (sortedEntries[i][0] === 'object') {
                const keySpan = document.createElement('span');
                keySpan.dataset.propertyKey = 'object';
                keySpan.dataset.propertyNamespace = 'treeProps';
                keySpan.textContent = 'object';
                propTable.insertTHeadRow({elements: [null, keySpan, this.#observable.getProperty('object').toString()], position: 'prepend'})
                break;
            }
            i++;
        }
        if (i < sortedEntries.length) {
            sortedEntries.splice(i, 1);
        }
        // - Add the treeKey to the top of the table
        const keySpan = document.createElement('span');
        keySpan.textContent = 'ID';
        keySpan.dataset.propertyKey = 'treeKey';
        keySpan.dataset.propertyNamespace = 'meta';
        propTable.insertTHeadRow({elements: [null, keySpan, this.#observable.getProperty('treeKey', 'meta').toString()], position: 'prepend'})
        // - Add the rest of the properties to the table
        for (const [key, val] of sortedEntries) {
            if (['from', 'to', 'type'].includes(key) && this.#observable.isParentChildLine()) {
                continue;
            }
            const keySpan = document.createElement('span');
            keySpan.textContent = key;
            keySpan.dataset.propertyKey = key;
            keySpan.dataset.propertyNamespace = 'treeProps';
            let deleteButton = null;
            // - Users should never be able to delete properties from components
            if (!FeatureEditModal.#nonDeletableProperties.includes(key) && !this.#observable.isComponentFeature()) {
                deleteButton = this.#getDeletePropertyButton(key);
            }
            propTable.insertTBodyRow({elements: [deleteButton, keySpan, this.#getValueTextInput(key, val)]});
        }
        if (this.#observable.isNode() && !this.#observable.isComponentFeature()) {
            const [lon, lat] = this.#observable.getCoordinates();
            let keySpan = document.createElement('span');
            keySpan.textContent = 'longitude';
            keySpan.dataset.propertyKey = 'longitude';
            // - longitude and latitude aren't in any property namespace
            propTable.insertTBodyRow({elements: [null, keySpan, this.#getValueTextInput('longitude', lon)], position: 'prepend'});
            keySpan = document.createElement('span');
            keySpan.textContent = 'latitude';
            keySpan.dataset.propertyKey = 'latitude';
            propTable.insertTBodyRow({elements: [null, keySpan, this.#getValueTextInput('latitude', lat)], position: 'prepend'});
        }
        // - I need this div to applying consistent CSS styling
        const div = document.createElement('div');
        // - Add buttons for regular nodes and lines
        if (!this.#observable.isComponentFeature() && !this.#observable.isConfigurationObject()) {
            const zoomButton = this.#getZoomButton();
            const deleteButton = this.#getDeleteFeatureButton();
            div.append(zoomButton);
            div.append(deleteButton);
            propTable.insertTBodyRow({elements: [this.#getAddPropertyButton(), null, div]});
        // - Add buttons for configuration objects
        } else if (!this.#observable.isComponentFeature()) {
            div.append(this.#getDeleteFeatureButton());
            propTable.insertTBodyRow({elements: [this.#getAddPropertyButton(), null, div]});
        } else {
            // - Add buttons for component configuration objects
            if (this.#observable.isConfigurationObject()) {
                div.append(this.#getAddConfigurationObjectButton());
                propTable.insertTBodyRow({elements: [div], colspans: [3]});
            // - Add buttons for node configuration objects
            } else if (this.#observable.isNode()) {
                div.append(this.#getAddNodeButton());
                propTable.insertTBodyRow({elements: [div], colspans: [3]});
            } else if (this.#observable.isLine()) {
                div.append(this.#getAddLineButton())
                propTable.insertTBodyRow({elements: [div], colspans: [3]});
            }
        }
    }

    /**
     * - Render arbitrary features
     */
    #renderArbitraryFeature(propTable) {
        for (const [key, val] of Object.entries(this.#observable.getProperties('meta'))) {
            if (key === 'TRACT') {
                propTable.insertTHeadRow({elements: [null, null, 'Census Tract', val.toString()], position: 'prepend'});
            } else if (key === 'OIP Score') {
                propTable.insertTBodyRow({elements: [null, null, 'OIP Score', val.toString()]});
            } else if (key === 'OIP Rating') {
                propTable.insertTBodyRow({elements: [null, null, 'OIP Rating', val.toString()]});
            } else {
                propTable.insertTBodyRow({elements: [null, null, key, val.toString()]});
            }
        }
    }

    /**
     * - Validate the just-inputed value for a value text input for an EXISTING feature
     * @param {string} propertyKey
     * @param {string} inputValue
     * @returns {boolean} whether the propertyKey and value are valid from a domain perspective
     */
    #valueTextInputIsValid(propertyKey, inputValue) {
        if (typeof propertyKey !== 'string') {
            throw TypeError('The "propertyKey" argument must be typeof string.');
        }
        if (typeof inputValue !== 'string') {
            throw TypeError('The "inputValue" argument must be typeof string.');
        }
        // - I am no longer always converting to lowercase because names are case-sensitive and therefore other properties should be too
        let validity;
        switch (propertyKey) {
            case 'type':
                inputValue = inputValue.toLowerCase();
                if (inputValue === 'parentchild') {
                    alert('The "type" property may not have a value of "parentChild".');
                    return false;
                }
                return true;
            case 'name':
                if (inputValue.trim() === '') {
                    alert('The "name" property cannot be blank.');
                    return false;
                }
                if (this.#controller.observableGraph.getObservables(ob => ob.hasProperty('name') && ob.getProperty('name') === inputValue).length > 0) {
                    alert(`The "name" property must be unique for all objects. The name "${inputValue}" is already used by another object.`);
                    return false;
                }
                return true;
            case 'from':
            case 'to':
                validity = this.#controller.observableGraph.getLineConnectionNameValidity(this.#observable, inputValue);
                if (!validity.isValid) {
                    alert(validity.reason);
                    return false;
                }
                if (propertyKey === 'from' && this.#observable.getProperty('to') === inputValue) {
                    alert(`This line already has the value "${inputValue}" for the property "to". Lines may not begin and end on the same object.`);
                    return false;
                }
                if (propertyKey === 'to' && this.#observable.getProperty('from') === inputValue) {
                    alert(`This line already has the value "${inputValue}" for the property "from". Lines may not begin and end on the same object.`);
                    return false;
                }
                return true;
            case 'parent':
                validity = this.#controller.observableGraph.getLineConnectionNameValidity(this.#observable, inputValue);
                if (!validity.isValid) {
                    alert(validity.reason);
                    return false;
                }
                return true;
            case 'latitude':
            case 'longitude':
                if (inputValue === '' || isNaN(+inputValue)) {
                    alert(`The value "${inputValue}" is not a valid number. A value for the "${propertyKey}" property must be a valid number.`);
                    return false;
                }
                return true;
            default:
                return true;
        }
    }
}

/**
 * - There's no need to create a function that returns a function if I use Function.prototype.bind() propertly
 * @param {Array} observables - an array of ObservableInterface instances
 * @returns {undefined}
 */
function zoom(observables) {
    if (!(observables instanceof Array)) {
        throw TypeError('The "observables" argument must be instanceof Array.');
    }
    if (observables.length === 1) {
        const observable = observables[0];
        const layer = observable.getObservers().filter(ob => ob instanceof LeafletLayer)[0];
        const leafletLayer = Object.values(layer.getLayer()._layers)[0];
        if (observable.isNode()) {
            const [lon, lat] = structuredClone(observable.getCoordinates());
            // - The max zoom level without losing the map is 19
            LeafletLayer.map.flyTo([lat, lon], 19, {duration: .3});
            layer.bindPopup();
            if (!leafletLayer.isPopupOpen()) {
                leafletLayer.openPopup();
            }
        } else if (observable.isLine()) {
            const [[lon1, lat1], [lon2, lat2]] = observable.getCoordinates();
            LeafletLayer.map.flyTo([(lat1 + lat2) / 2, (lon1 + lon2) / 2], 19, {duration: .3});
            if (!leafletLayer.isPopupOpen()) {
                leafletLayer.openPopup();
            }
        } else {
            throw Error('Zoom button is only supported for nodes and lines.');
            //let coordinates;
            //if (observable.isPolygon()) {
            //    coordinates = observable.getCoordinates().flat(1);
            //} else if (observable.isMultiPolygon()) {
            //    coordinates = observable.getCoordinates().flat(2);
            //} else {
            //    return;
            //}
            //const lons = [];
            //const lats = [];
            //coordinates.forEach(ary => { lons.push(ary[0]); lats.push(ary[1]); });
            //LeafletLayer.map.flyToBounds([
            //    [Math.min.apply(null, lats), Math.min.apply(null, lons)],
            //    [Math.max.apply(null, lats), Math.max.apply(null, lons)]],
            //    {duration: .3});
            //if (!leafletLayer.isPopupOpen()) {
            //    leafletLayer.openPopup();
            //}
        }
    } else {
        const lons = [];
        const lats = [];
        observables.forEach(ob => {
            if (ob.isNode()) {
                const [lon, lat] = ob.getCoordinates();
                lons.push(lon);
                lats.push(lat);
            } else if (ob.isLine()) {
                const [[lon1, lat1], [lon2, lat2]] = ob.getCoordinates();
                lons.push(...[lon1, lon2]);
                lats.push(...[lat1, lat2]);
            }
        });
        LeafletLayer.map.flyToBounds([
            [Math.min.apply(null, lats), Math.min.apply(null, lons)],
            [Math.max.apply(null, lats), Math.max.apply(null, lons)],
            19,
            {duration: .3}
        ]);
    }
}