export { GeojsonModal };
import { Feature, UnsupportedOperationError } from './feature.js';
import { FeatureController } from './featureController.js';
import { LeafletLayer } from './leafletLayer.js';
import { PropTable } from '../v4/ui-components/prop-table/prop-table.js';
import { IconLabelButton } from '../v4/ui-components/iconlabel-button/iconlabel-button.js';
import { LoadingSpan } from '../v4/ui-components/loading-span/loading-span.js';

// - Test data can be found at omf/scratch/CIGAR/geoJsonLeaflet

class GeojsonModal { // implements ModalInterface, ObserverInterface
    #controller;                        // - ControllerInterface instance
    #propTable;                         // - PropTable instance
    #observables;                       // - An array of ObservableInterface instances
    #removed;                           // - Whether this ColorModal instance has already been deleted
    static filenameToLayerGroup = {};   // - Container for LayerGroups. This must be static and public because the LeafletLayer.map needs an event listener with an event handler that redraw the layers

    /**
     * @param {Array} observables - an array of ObservableInterface instances 
     * @param {FeatureController} controller - a ControllerInterface instance
     */
    constructor(observables, controller) {
        if (!(observables instanceof Array)) {
            throw TypeError('The "observables" argumnet must be instanceof Array.');
        }
        if (!(controller instanceof FeatureController)) {
            throw Error('The "controller" argument must be instanceof FeatureController.');
        }
        this.#controller = controller;
        //this.#filenameToLayerGroup = {};
        this.#propTable = null;
        this.#observables = observables;
        this.#observables.forEach(ob => ob.registerObserver(this));
        this.#removed = false;
        LeafletLayer.map.on('overlayadd', GeojsonModal.forceRedraw);
        this.renderContent();
        this.refreshContent();
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
            observable.removeObserver(this);
            const index = this.#observables.indexOf(observable);
            if (index > -1) {
                this.#observables.splice(index, 1);
            } else {
                throw Error('The observable was not found in this.#observables.');
            }
            if (this.#observables.length === 0) {
                this.remove();
            } else {
                this.#updateLayerGroups();
                this.refreshContent();
            }
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
        this.#updateLayerGroups();
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
        this.#updateLayerGroups();
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

    // - Go through the attachments object and display existing GeoJSON files

    /**
     * @returns {undefined}
     */
    refreshContent() {
        const fileListTable = new PropTable();
        fileListTable.div.classList.add('fileListTable');
        if (Object.values(GeojsonModal.filenameToLayerGroup).length > 0) {
            fileListTable.insertTBodyRow({elements: ['Filename', 'Show GeoJSON on page load']});
        }
        const that = this;
        const attachments = this.#controller.observableGraph.getObservable('omd').getProperty('attachments', 'meta');
        for (const filename of Object.keys(GeojsonModal.filenameToLayerGroup)) {
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.name = 'displayOnLoad';
            checkbox.addEventListener('change', function() {
                for (const [fname, obj] of Object.entries(attachments.geojsonFiles)) {
                    if (fname === filename) {
                        if (this.checked) {
                            obj.displayOnLoad = true;
                        } else {
                            delete obj.displayOnLoad
                        }
                    } else {
                        // - Do nothing
                    }
                }
            });
            if (attachments.geojsonFiles[filename].displayOnLoad) {
                checkbox.checked = true;
            }
            const removeButton = new IconLabelButton({text: 'Remove'});
            removeButton.button.classList.add('-red');
            removeButton.button.getElementsByClassName('label')[0].classList.add('-white');
            removeButton.button.addEventListener('click', () => {
                if (attachments.hasOwnProperty('geojsonFiles')) {
                    delete attachments.geojsonFiles[filename];
                    LeafletLayer.map.removeLayer(GeojsonModal.filenameToLayerGroup[filename].layerGroup);
                    LeafletLayer.control.removeLayer(GeojsonModal.filenameToLayerGroup[filename].layerGroup);
                    delete GeojsonModal.filenameToLayerGroup[filename];
                    if (Object.keys(attachments.geojsonFiles).length === 0) {
                        delete attachments.geojsonFiles;
                    }
                    that.refreshContent();
                }
            });
            fileListTable.insertTBodyRow({elements: [filename, checkbox, removeButton.button]});
        }
        const existingRow = this.#propTable.div.getElementsByClassName('proptablediv');
        // - There was NOT already a fileListTable in place, so insert this fileListTable
        if (existingRow.length === 0) {
            this.#propTable.insertTBodyRow({elements: [fileListTable.div], colspans: [2]});
        // - There was already a fileListTable in place. Replace it with this fileListTable
        } else {
            existingRow[0].replaceWith(fileListTable.div);
        }
    }

    /**
     * @returns {undefined}
     */
    remove() {
        if (!this.#removed) {
            this.#observables.forEach(ob => ob.removeObserver(this));
            this.#observables = null;
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
        propTable.div.id = 'geojsonModal';
        propTable.div.addEventListener('click', function(e) {
            e.stopPropagation();
        });
        propTable.insertTHeadRow({elements: ['Add GeoJson'], colspans: [2]});
        const geojsonInput = document.createElement('input');
        geojsonInput.type = 'file';
        geojsonInput.accept = '.geojson';
        geojsonInput.required = true;
        geojsonInput.id = 'geojsonInput';
        const that = this;
        const loadingSpan = new LoadingSpan();
        loadingSpan.span.classList.add('-yellow', '-hidden');
        propTable.insertTHeadRow({elements: [loadingSpan.span], position: 'prepend', colspans: [2]})
        const attachments = this.#controller.observableGraph.getObservable('omd').getProperty('attachments', 'meta');
        geojsonInput.addEventListener('change', async function() {
            const file = this.files[0];
            const text = await file.text();
            let featureCollection;
            try {
                featureCollection = JSON.parse(text);
                loadingSpan.update({text: '', show: false});
                if (!attachments.hasOwnProperty('geojsonFiles')) {
                    attachments.geojsonFiles = {};
                }
                attachments.geojsonFiles[file.name] = {
                    json: JSON.stringify(featureCollection)
                }
                that.#updateLayerGroups();
                that.refreshContent();
            } catch (e) {
                loadingSpan.update({text: `There was an error "${e.message}" when parsing the JSON file "${file.name}". Please double-check the JSON formatting.`, show: true, showGif: false});
            }
        });
        const geojsonLabel = document.createElement('label');
        geojsonLabel.htmlFor = 'geojsonInput';
        geojsonLabel.innerHTML = 'Add a file containing a GeoJSON feature collection (.geojson)';
        propTable.insertTBodyRow({elements: [geojsonLabel, geojsonInput]});
        if (this.#propTable === null) {
            this.#propTable = propTable;
        }
        if (document.body.contains(this.#propTable.div)) {
            this.#propTable.div.replaceWith(propTable.div);
            this.#propTable = propTable;
        }
        this.#updateLayerGroups(true);
    }

    // ********************
    // ** Public methods **
    // ********************

    /**
     * - This must be public because the LeafletLayer.map needs an event listener with an event handler that redraw the layers
     */
    static forceRedraw() {
        // - Remove the event listener to prevent infinite recursion
        LeafletLayer.map.off('overlayadd', GeojsonModal.forceRedraw);
        let layerGroups = Object.values(GeojsonModal.filenameToLayerGroup).map(obj => {
            return obj.layerGroup;
        });
        layerGroups = [...layerGroups, LeafletLayer.parentChildLineLayers, LeafletLayer.lineLayers, LeafletLayer.nodeLayers, LeafletLayer.nodeClusterLayers];
        for (const layerGroup of layerGroups) {
            LeafletLayer.map.removeLayer(layerGroup);
            LeafletLayer.map.addLayer(layerGroup);
        }
        // - Re-add the event listener back to handle future events
        LeafletLayer.map.on('overlayadd', GeojsonModal.forceRedraw);
    }

    // *********************
    // ** Private methods **
    // *********************

    /**
     * - Iterate through the attachments.geojsonFiles object. For each file, do the following:
     *  - Parse the json string into a GeoJSON featureCollection
     *  - Iterate through the features of the feature collection and create Feature instances and LeafletLayer instances
     *  - Add the LeafletLayer instances to a new LayerGroup that has the same name as the file
     *  - Do not add the Feature instances to a FeatureGraph (at least, not yet)
     *  - Add the LayerGroup to the map
     *      - In order to not keep adding the same features over and over again, here's what I'll do:
     *          - I consider filenames to be unique identifiers for a set of Features/LeafletLayers
     *          - Have a "geojsonFiles" object as a property of this GeojsonModal. Keys are filenames and values are LayerGroup instances. If a file
     *            is deleted, modify the attachments object, remove the LayerGroup from the map, and delete the LayerGroup from the geojsonFiles
     *            object. If a file is added, modify the attachments object, create a new LayerGroup object, add the LeafletLayers to the LayerGroup,
     *            overwrite the geojsonFiles object with the new layer group (and remove the matching LayerGroup from the map if there was one), and
     *            add the new LayerGroup to the map
     * - In this way, the attachments object will be synchronized with the geojsonFiles object. The user will be able to show/hide the LayerGroups via
     *   the normal Leaflet controls
     * - When is this function called? On renderContent(), in response to a file upload, and if a GeoJSON file is edited in the attachments modal
     * @param {boolean} renderContent - whether this function was called on the initial renderContent() call
     * @returns {undefined}
     */
    #updateLayerGroups(renderContent=false) {
        const attachments = this.#controller.observableGraph.getObservable('omd').getProperty('attachments', 'meta');
        if (attachments.hasOwnProperty('geojsonFiles')) {
            const that = this;
            for (const [filename, obj] of Object.entries(attachments.geojsonFiles)) {
                try {
                    const featureCollection = JSON.parse(obj.json);
                    const layerGroup = L.featureGroup();
                    featureCollection.features.map(f => new Feature(f)).map(f => new LeafletLayer(f, that.#controller)).forEach(ll => layerGroup.addLayer(ll.getLayer()));
                    if (GeojsonModal.filenameToLayerGroup.hasOwnProperty(filename)) {
                        LeafletLayer.map.removeLayer(GeojsonModal.filenameToLayerGroup[filename].layerGroup);
                        LeafletLayer.control.removeLayer(GeojsonModal.filenameToLayerGroup[filename].layerGroup);
                    }
                    GeojsonModal.filenameToLayerGroup[filename] = {
                        layerGroup: layerGroup,
                    };
                    LeafletLayer.control.addOverlay(layerGroup, filename);
                    if (renderContent) {
                        if (obj.displayOnLoad) {
                            layerGroup.addTo(LeafletLayer.map);
                        }
                    } else {
                        layerGroup.addTo(LeafletLayer.map);
                    }
                } catch (e) {
                    console.log(`The GeoJSON in the attachments object could not be parsed: ${e}`);
                }
            }
        }
    }
}